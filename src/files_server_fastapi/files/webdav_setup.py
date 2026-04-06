"""
webdav_setup.py — Servidor WebDAV integrado en FastAPI.

Permite que Microsoft Office (Word, Excel, PowerPoint) abra archivos
directamente desde el servidor, los edite y los guarde de vuelta sin
que el usuario tenga que descargar ni re-subir nada manualmente.

Protocolo de apertura que genera el endpoint /files/open-url:
    ms-word:ofe|u|http://servidor/webdav/AREA/subpath/archivo.docx

Todas las rutas y configuraciones vienen del .env a través de constants.py.
Los archivos se sirven desde el mismo directorio que Samba (FILES_BASE_DIR).
Samba y WebDAV coexisten sin interferirse — dos "ventanas" al mismo directorio.
"""

import psycopg2
from passlib.context import CryptContext
from wsgidav.wsgidav_app import WsgiDAVApp
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.dc.base_dc import BaseDomainController

from files_server_fastapi.files.constants import (
    BASE_DIR,
    WEBDAV_DATABASE_URL,
    WEBDAV_AUTH_REALM,
)

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class PostgresDomainController(BaseDomainController):
    """
    Controlador de dominio WebDAV que verifica credenciales Basic Auth
    contra la tabla de usuarios en PostgreSQL.

    Office envía el email y contraseña en cada sesión de apertura.
    Windows Credential Manager los guarda automáticamente para no
    volver a pedirlos en aperturas posteriores del mismo servidor.
    """

    def __init__(self, wsgidav_app, config):
        super().__init__(wsgidav_app, config)
        # Lee de constants.py (que a su vez leen del .env)
        self._db_url = WEBDAV_DATABASE_URL
        self._realm  = WEBDAV_AUTH_REALM

    def get_domain_realm(self, path_info, environ):
        return self._realm

    def require_authentication(self, realm, environ):
        return True

    def supports_http_digest_auth(self):
        # Solo Basic Auth — más compatible con Office
        return False

    def basic_auth_user(self, realm, user_name, password, environ):
        """
        Verifica email + contraseña contra PostgreSQL de forma síncrona.
        Usa psycopg2 (no asyncpg) porque wsgidav es app WSGI tradicional.
        """
        if not self._db_url:
            print(
                "[WebDAV] ⚠️  WEBDAV_DATABASE_URL no está en el .env. "
                "Agrega: WEBDAV_DATABASE_URL=postgresql://user:pass@host:5432/bd"
            )
            return False

        try:
            conn = psycopg2.connect(self._db_url)
            cur  = conn.cursor()
            cur.execute(
                'SELECT hashed_password FROM "user" '
                'WHERE email = %s AND is_active = TRUE',
                (user_name,),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()

            if row and _pwd_context.verify(password, row[0]):
                return True

        except Exception as e:
            print(f"[WebDAV] ❌ Error de autenticación: {e}")

        return False

    def digest_auth_user(self, realm, user_name, environ):
        return None


def create_webdav_app() -> WsgiDAVApp:
    """
    Crea y devuelve la aplicación WSGI WebDAV lista para montar en FastAPI.

    Lee BASE_DIR desde constants.py (variable FILES_BASE_DIR del .env).
    Sirve los archivos del mismo directorio que Samba — coexisten sin conflicto.

    Uso en main.py:
        from starlette.middleware.wsgi import WSGIMiddleware
        from files_server_fastapi import get_webdav_wsgi_app

        app.mount("/webdav", WSGIMiddleware(get_webdav_wsgi_app()))

    Raises:
        ValueError: Si FILES_BASE_DIR no está configurado en el .env.
    """
    if not BASE_DIR:
        raise ValueError(
            "[WebDAV] FILES_BASE_DIR no está en el .env. "
            "Agrega: FILES_BASE_DIR=/ruta/a/tus/archivos"
        )

    provider = FilesystemProvider(BASE_DIR, readonly=False)

    config = {
        "provider_mapping": {"/": provider},
        "http_authenticator": {
            "domain_controller":  PostgresDomainController,
            "accept_basic":       True,
            "accept_digest":      False,
            "default_to_digest":  False,
        },
        # Lock manager en memoria — Office lo usa para bloquear el archivo
        # mientras lo edita (peticiones LOCK/UNLOCK de WebDAV)
        "lock_storage":    True,
        # Property manager para metadatos WebDAV estándar
        "property_manager": True,
        "verbose": 1,
        "logging": {"enable_loggers": []},
    }

    return WsgiDAVApp(config)
