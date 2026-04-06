"""
webdav_setup.py — Configura y crea la aplicación WSGI WebDAV para edición
en tiempo real de archivos Office (Word, Excel, PowerPoint).

Protocolo de apertura:
  ms-word:ofe|u|https://servidor/webdav/AREA/subpath/file.docx

Flujo completo:
  1. El usuario hace clic en "Abrir" en el frontend
  2. El frontend llama a GET /files/open-url y recibe la URL de Office Protocol
  3. El navegador lanza la URL ms-word:ofe|u|https://...
  4. Word/Excel se abre y autentica contra este endpoint WebDAV (Basic Auth)
  5. El usuario edita el archivo normalmente
  6. Al guardar (Ctrl+S), Office hace un PUT a este WebDAV → cambios guardados en servidor

Requerimiento de entorno:
  WEBDAV_DATABASE_URL  — Cadena de conexión PostgreSQL síncrona (psycopg2)
                         Ejemplo: postgresql://user:pass@localhost:5432/dbname
"""

import os
import psycopg2
from passlib.context import CryptContext
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.dc.base_dc import BaseDomainController

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class IMBODomainController(BaseDomainController):
    """
    Controlador de dominio WebDAV que valida credenciales Basic Auth
    contra la base de datos PostgreSQL del sistema IMBO.

    Office enviará el usuario (email) y contraseña en cada sesión.
    Windows Credential Manager guardará las credenciales para no pedirlas
    de nuevo en aperturas posteriores.
    """

    def __init__(self, wsgidav_app, config):
        super().__init__(wsgidav_app, config)
        # Permite pasar la URL desde el config de wsgidav, o leer del entorno
        self._db_url = config.get("imbo_db_url") or os.getenv("WEBDAV_DATABASE_URL", "")

    def get_domain_realm(self, path_info, environ):
        return "IMBO Ficheros"

    def require_authentication(self, realm, environ):
        return True

    def supports_http_digest_auth(self):
        # Usamos únicamente Basic Auth (más simple y compatible con Office)
        return False

    def basic_auth_user(self, realm, user_name, password, environ):
        """
        Verifica email + contraseña contra la tabla 'user' de PostgreSQL.
        Usa psycopg2 (síncrono) porque wsgidav es un app WSGI tradicional.
        """
        if not self._db_url:
            print("⚠️  [WebDAV] WEBDAV_DATABASE_URL no está configurada en el entorno.")
            return False

        try:
            conn = psycopg2.connect(self._db_url)
            cur = conn.cursor()
            # La tabla se llama 'user' (SQLModel default para clase User)
            # Si en tu BD se llama 'users', cámbialo aquí
            cur.execute(
                'SELECT hashed_password FROM "user" WHERE email = %s AND is_active = TRUE',
                (user_name,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and _pwd_context.verify(password, row[0]):
                return True

        except Exception as e:
            print(f"❌ [WebDAV] Error de autenticación: {e}")

        return False

    def digest_auth_user(self, realm, user_name, environ):
        # Digest no soportado — solo Basic Auth
        return None


def create_webdav_app(base_dir: str) -> WsgiDAVApp:
    """
    Crea y devuelve la aplicación WSGI WebDAV configurada para servir
    los archivos desde `base_dir` con autenticación Basic Auth.

    Se monta en FastAPI usando Starlette WSGIMiddleware:
        app.mount("/webdav", WSGIMiddleware(create_webdav_app(BASE_DIR)))

    Args:
        base_dir: Ruta absoluta al directorio raíz de archivos en el servidor.

    Returns:
        Instancia de WsgiDAVApp lista para montar.
    """
    if not base_dir:
        raise ValueError(
            "WebDAV: FILES_BASE_DIR no está configurado. "
            "Agrega FILES_BASE_DIR=/ruta/a/archivos en tu .env"
        )

    provider = FilesystemProvider(base_dir, readonly=False)

    config = {
        "provider_mapping": {"/": provider},
        # Pasa la DB URL al domain controller
        "imbo_db_url": os.getenv("WEBDAV_DATABASE_URL", ""),
        "http_authenticator": {
            "domain_controller": IMBODomainController,
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        # Lock manager en memoria — necesario para que Office pueda bloquear
        # el archivo mientras lo edita (LOCK/UNLOCK requests)
        "lock_storage": True,
        # Property manager en memoria para metadatos WebDAV
        "property_manager": True,
        "verbose": 1,
        "logging": {
            "enable_loggers": [],
        },
    }

    return WsgiDAVApp(config)
