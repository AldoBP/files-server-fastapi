#!/usr/bin/env python3
"""
sync_users.py — Sincronizador de Permisos Samba
===============================================
Lee usuarios de PostgreSQL y aplica permisos Linux/Samba de dos formas:

  MODO BASE (por Rol):
    Si un usuario NO tiene rutas específicas en user_ruta_access, se aplica
    el permiso de su rol sobre toda la carpeta de su área.

  MODO GRANULAR (por Ruta):
    Si un usuario SÍ tiene rutas asignadas en user_ruta_access, se aplica:
    - Permisos específicos en cada subcarpeta definida en user_ruta_access

Roles soportados (dinámicos desde BD y .env).
Permisos de visualización:
  - allow_view      → linux_acl "r-x" (puede navegar subcarpetas en Samba)
  - allow_view_root → linux_acl "r--" (solo ve la raíz del área asignada)

Configuración (.env en la raíz del proyecto):
  SYNC_DB_NAME     — Nombre de la base de datos        (default: files_server_db)
  SYNC_DB_USER     — Usuario de conexión               (default: sync_reader)
  SYNC_DB_PASSWORD — Contraseña de conexión            (requerido, sin default seguro)
  SYNC_DB_HOST     — Host del servidor PostgreSQL      (default: 127.0.0.1)
  SYNC_DB_PORT     — Puerto del servidor PostgreSQL    (default: 5432)
  SYNC_BASE_DIR    — Ruta raíz del share Samba         (default: /srv/samba_data)
  SYNC_LOG_FILE    — Ruta del archivo de log           (default: /var/log/sync_users.log)

Uso:
  python sync_users.py             → Modo producción
  python sync_users.py --dry-run   → Simula sin aplicar cambios
"""

import os
import sys
import logging
import subprocess
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

# ─── Cargar .env desde la raíz del proyecto ─────────────────────────────────
# Busca el .env en el mismo directorio donde está este script, sin importar
# desde qué carpeta se ejecute el comando.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

# ─── Configuración (leída del .env o variables de entorno del sistema) ────────
# Reutiliza las variables que ya existen en el .env del proyecto.
# Prioridad: primero busca DB_CONNECTIONS__DEFAULT__*, luego SYNC_* como fallback.
DB_CONFIG = {
    "dbname":   os.getenv("DB_CONNECTIONS__DEFAULT__DATABASE",
                os.getenv("SYNC_DB_NAME",     "files_server_db")),
    "user":     os.getenv("DB_CONNECTIONS__DEFAULT__USERNAME",
                os.getenv("SYNC_DB_USER",     "sync_reader")),
    "password": os.getenv("DB_CONNECTIONS__DEFAULT__PASSWORD",
                os.getenv("SYNC_DB_PASSWORD", "")),
    "host":     os.getenv("DB_CONNECTIONS__DEFAULT__HOST",
                os.getenv("SYNC_DB_HOST",     "127.0.0.1")),
    "port":     os.getenv("DB_CONNECTIONS__DEFAULT__PORT",
                os.getenv("SYNC_DB_PORT",     "5432")),
}

# FILES_BASE_DIR ya existe en el .env; SYNC_BASE_DIR como fallback.
BASE_DIR = os.getenv("FILES_BASE_DIR",
           os.getenv("SYNC_BASE_DIR", "/srv/samba_data"))

# Solo LOG_FILE es propio de sync_users (no tiene equivalente en el .env base).
LOG_FILE = os.getenv("SYNC_LOG_FILE", "/var/log/sync_users.log")

if not os.access(os.path.dirname(LOG_FILE), os.W_OK):
    LOG_FILE = "/tmp/sync_users.log"

# Roles y Permisos Globales (Fallback si no están en BD)
GLOBAL_ADMIN_ROLE = os.getenv("GLOBAL_ADMIN_ROLE", "SUPER_ADMIN").upper()
AREA_ADMIN_ROLE = os.getenv("AREA_ADMIN_ROLE", "AREA_ADMIN").upper()
_default_perms_str = os.getenv("DEFAULT_AREA_PERMISSIONS", "AREA_ADMIN:web_full,EDITOR:web_edit,VIEWER:web_view")

# Mapeo estático manual para fallbacks (por si la BD de permisos está vacía o usamos fallback de rol)
_STATIC_ACL_MAP = {
    "web_full": "rwx",
    "web_upload": "rwX",
    "web_edit": "rwX",
    "web_view": "r-X",
    "deny_all": None,
}

# ─────────────────────────────────────────────────────────────────────────────

# Estas variables se poblarán dinámicamente desde la BD en cada ejecución
PERMISOS_POR_ROL: dict[str, str] = {}
ACCESS_TYPE_MAP:  dict[str, str | None] = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ─── Utilidades ───────────────────────────────────────────────────────────────

def ejecutar(comando: str, dry_run: bool = False) -> bool:
    if dry_run:
        log.info(f"  [DRY-RUN] {comando}")
        return True
    result = subprocess.run(
        comando, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    if result.returncode != 0:
        log.warning(f"  ⚠️  Fallo (Código {result.returncode}): {comando}")
        if result.stderr.strip():
            log.warning(f"     Detalle: {result.stderr.strip()}")
        return False
    return True


def email_a_linux_user(email: str) -> str:
    return email.replace("@", "_").replace(".", "_").lower()


def ruta_absoluta(ruta: str) -> str:
    return f"{BASE_DIR}/{ruta.lstrip('/')}"


def icono_acl(acl: str | None) -> str:
    """Retorna un emoji representativo del nivel de acceso."""
    if acl is None:
        return "🚫"
    if "w" in acl:
        return "✅"
    if "r" in acl:
        return "👁️"
    return "🚫"


# ─── Queries SQL ──────────────────────────────────────────────────────────────

QUERY_USUARIOS = """
    SELECT
        u.id       AS user_id,
        u.email,
        ue.samba_enabled,
        r.role_name,
        a.area_name
    FROM users u
    JOIN users_extend ue ON u.id = ue.user_id
    JOIN rol r           ON ue.rol_id = r.id
    JOIN area a          ON ue.area_id = a.id
    WHERE u.is_verified = true
"""

QUERY_RUTAS_USUARIO = """
    SELECT
        rt.ruta,
        ura.access_type,
        UPPER(TRIM(a.area_name)) AS area_de_la_ruta
    FROM user_ruta_access ura
    JOIN rutas rt  ON ura.ruta_id = rt.id
    JOIN area a    ON rt.area_id  = a.id
    WHERE ura.user_id = %s
    ORDER BY rt.ruta;
"""

QUERY_TODAS_AREAS = "SELECT UPPER(TRIM(area_name)) FROM area;"


# ─── Funciones de ACL ─────────────────────────────────────────────────────────

def asegurar_x_en_acl(acl: str | None) -> str | None:
    """Convierte 'rw-' en 'rwX' o 'r--' en 'r-X' para que los directorios sean navegables."""
    if not acl or acl in ["---", "-", ""]:
        return acl
    # Si tiene lectura o escritura y no tiene x/X explícito, agregar X
    if "r" in acl or "w" in acl:
        if "x" not in acl and "X" not in acl:
            return acl[:2] + "X"
    return acl

def limpiar_acls_usuario(username: str, base_dir: str, todas_areas: list, dry_run: bool):
    ejecutar(f'setfacl -R -x u:{username} "{base_dir}"', dry_run)


def aplicar_aislamiento_raiz(
    username: str,
    base_dir: str,
    todas_areas: list,
    areas_permitidas: set,
    dry_run: bool,
):
    # Permiso de LECTURA y EJECUCIÓN solo para listar la raíz del dominio en Windows
    ejecutar(f'setfacl -m u:{username}:r-x "{base_dir}"', dry_run)

    for area in todas_areas:
        ruta_area = f"{base_dir}/{area}"

        if not dry_run and not os.path.isdir(ruta_area):
            log.warning(f"   ⚠️  Área '{area}' no existe en disco, se omite: {ruta_area}")
            continue

        # Bloqueo total recursivo a todas las áreas por defecto
        ejecutar(f'setfacl -R -m u:{username}:--- "{ruta_area}"', dry_run)
        ejecutar(f'setfacl -R -d -m u:{username}:--- "{ruta_area}"', dry_run)

        if area in areas_permitidas:
            # Abrir la puerta solo a la carpeta principal del área
            ejecutar(f'setfacl -m u:{username}:r-x "{ruta_area}"', dry_run)
            log.info(f"   🔓 Navegación permitida en raíz de → {ruta_area}")
        else:
            log.info(f"   🚫 Área bloqueada totalmente (---): {ruta_area}")


def aplicar_acl_granular(
    username: str,
    rutas_usuario: list,
    carpeta_area_nativa: str,
    dry_run: bool,
) -> bool:
    """
    Aplica permisos granulares (excepciones) sobre rutas específicas.
    - Para rutas en el ÁREA NATIVA del usuario: solo aplica el permiso en el destino.
    - Para rutas en ÁREAS EXTERNAS: da r-x en cada carpeta intermedia para
      que el usuario pueda navegar hasta llegar al destino.

    Los permisos de visualización son compatibles:
      allow_view      → r-x  (puede navegar y abrir, no modifica)
      allow_view_root → r--  (solo ve el directorio raíz asignado, no entra a subcarpetas)

    IMPORTANTE: Nunca se crean directorios. Si la ruta no existe en disco, se omite.
    """
    ok_global = True
    for path_ruta, access_type, area_ruta in rutas_usuario:
        abs_path = ruta_absoluta(path_ruta)
        acl = ACCESS_TYPE_MAP.get(access_type)

        if acl is None:
            # deny_all: bloquear si la ruta existe
            if not dry_run and not os.path.exists(abs_path):
                log.warning(f"   ⚠️  Ruta no existe en disco, se omite deny_all: {abs_path}")
                continue
            log.info(f"   🚫 deny_all explícito → {abs_path}")
            ejecutar(f'setfacl -R -m u:{username}:--- "{abs_path}"', dry_run)
            ejecutar(f'setfacl -R -d -m u:{username}:--- "{abs_path}"', dry_run)
        else:
            if not dry_run and not os.path.exists(abs_path):
                log.warning(f"   ⚠️  Ruta no existe en disco, se omite ACL granular: {abs_path}")
                continue

            partes = path_ruta.strip("/").split("/")
            first_area = partes[0].upper()

            # Solo caminar padres si la ruta pertenece a un ÁREA EXTERNA
            if first_area != carpeta_area_nativa:
                base_temp = BASE_DIR
                for i in range(len(partes) - 1):
                    base_temp += f"/{partes[i]}"
                    if not dry_run and not os.path.isdir(base_temp):
                        log.warning(f"   ⚠️  Carpeta intermedia no existe: {base_temp}")
                        continue
                    ejecutar(f'setfacl -m u:{username}:r-x "{base_temp}"', dry_run)

            ok1 = ejecutar(f'setfacl -R -m u:{username}:{acl} "{abs_path}"', dry_run)
            ok2 = ejecutar(f'setfacl -R -d -m u:{username}:{acl} "{abs_path}"', dry_run)
            log.info(f"   {icono_acl(acl)} {access_type} ({acl}) → {abs_path}")
            if not (ok1 and ok2):
                ok_global = False
    return ok_global


def aplicar_acl_base(username: str, permisos: str, ruta: str, dry_run: bool) -> bool:
    if not dry_run and not os.path.isdir(ruta):
        log.warning(f"   ⚠️  Carpeta base no existe en disco, se omite: {ruta}")
        return False
    
    # Aplicar siempre la X condicional a directorios
    permisos_dir = asegurar_x_en_acl(permisos)
    
    ok1 = ejecutar(f'setfacl -R -m u:{username}:{permisos_dir} "{ruta}"', dry_run)
    ok2 = ejecutar(f'setfacl -R -d -m u:{username}:{permisos_dir} "{ruta}"', dry_run)
    return ok1 and ok2


# ─── Proceso principal ────────────────────────────────────────────────────────

def sincronizar_samba(dry_run: bool = False, target_user_id: int | None = None):
    modo = "DRY-RUN" if dry_run else "PRODUCCIÓN"
    if target_user_id:
        modo += f" (Solo Usuario ID {target_user_id})"

    log.info("═══════════════════════════════════════")
    log.info(f"🔄 Iniciando sincronización de permisos Samba — Modo: {modo}")
    log.info("═══════════════════════════════════════")

    try:
        global PERMISOS_POR_ROL, ACCESS_TYPE_MAP

        conn = psycopg2.connect(**DB_CONFIG)
        cursor_usuarios = conn.cursor()
        cursor_rutas    = conn.cursor()
        cursor_areas    = conn.cursor()
        cursor_config   = conn.cursor()

        # Cargar mapeo fastapi_action → linux_acl (dinámico desde la tabla permisos)
        # Incluye automáticamente allow_view ("r-x") y allow_view_root ("r--")
        def _smart_acl(action: str, acl_str: str) -> str | None:
            if not acl_str or acl_str in ["---", "-", ""]:
                return None
            
            # Ignoramos el 'r--' de la base de datos para web_edit y forzamos 'rw-'
            # para que el script de Samba asigne rwX y permita editar en Windows,
            # manteniendo la BD intacta para la App Web.
            if action == "web_edit":
                acl_str = "rw-"
                
            # Si el permiso NO debe entrar a subcarpetas (ej. view_root), lo dejamos intacto
            if "root" in action.lower():
                return acl_str
            return asegurar_x_en_acl(acl_str)

        cursor_config.execute("SELECT fastapi_action, linux_acl FROM permisos;")
        ACCESS_TYPE_MAP = {
            row[0]: _smart_acl(row[0], row[1])
            for row in cursor_config.fetchall()
        }
        if "deny_all" not in ACCESS_TYPE_MAP:
            ACCESS_TYPE_MAP["deny_all"] = None
        log.info(f"📋 ACCESS_TYPE_MAP cargado: {ACCESS_TYPE_MAP}")

        # La tabla permiso_rol fue eliminada en favor de configurar permisos de rol
        # exclusivamente a través del archivo .env (DEFAULT_AREA_PERMISSIONS).
        PERMISOS_POR_ROL = {}

        # Inyectar fallbacks desde el .env si no existen en la base de datos (Ej: tabla permiso_rol vacía)
        # 1. Admin Global
        if GLOBAL_ADMIN_ROLE not in PERMISOS_POR_ROL:
            PERMISOS_POR_ROL[GLOBAL_ADMIN_ROLE] = "rwx"

        # 2. Roles por defecto (Area Admin, Editor, Viewer, etc)
        if _default_perms_str:
            for pair in _default_perms_str.split(","):
                if ":" in pair:
                    role_str, p_str = pair.split(":", 1)
                    role_key = role_str.strip().upper()
                    if role_key not in PERMISOS_POR_ROL:
                        # Convertir web_full -> rwx
                        linux_acl_fallback = _STATIC_ACL_MAP.get(p_str.strip(), "r-x")
                        if linux_acl_fallback is not None:
                            PERMISOS_POR_ROL[role_key] = linux_acl_fallback

        log.info(f"📋 PERMISOS_POR_ROL cargado/inyectado: {PERMISOS_POR_ROL}")

        cursor_config.close()

        cursor_areas.execute(QUERY_TODAS_AREAS)
        todas_areas = [row[0] for row in cursor_areas.fetchall()]
        log.info(f"🗺️  Áreas en sistema: {', '.join(todas_areas)}")
        cursor_areas.close()

        query_usuarios_final = QUERY_USUARIOS
        params_usuarios = ()
        if target_user_id:
            query_usuarios_final += " AND u.id = %s "
            params_usuarios = (target_user_id,)

        query_usuarios_final += " ORDER BY r.role_name, u.email;"

        cursor_usuarios.execute(query_usuarios_final, params_usuarios)
        registros = cursor_usuarios.fetchall()

        if not registros:
            log.info("ℹ️  No hay usuarios verificados para procesar.")
            return

        log.info(f"📋 Usuarios en DB: {len(registros)}")
        procesados, errores = 0, 0

        for user_id, email, samba_enabled, role_name, area_name in registros:
            username     = email_a_linux_user(email)
            role_upper   = role_name.strip().upper()
            carpeta_area = area_name.strip().upper()

            log.info("─────────────────────────────────────")
            log.info(f"⚙️  {username}  |  Rol: {role_upper}  |  Área: {carpeta_area}")

            if role_upper not in PERMISOS_POR_ROL:
                log.error(f"   ❌ Rol '{role_upper}' no tiene permisos configurados en la BD.")
                errores += 1
                continue

            # Crear usuario Linux si no existe
            if not ejecutar(
                f"id -u {username} >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin {username}",
                dry_run,
            ):
                log.error("   ❌ No se pudo crear/validar el usuario Linux.")
                errores += 1
                continue

            # Sincronizar estado Samba (Habilitar o deshabilitar)
            if samba_enabled:
                ok_smb = ejecutar(f"smbpasswd -e {username}", dry_run)
                if not ok_smb:
                    log.error("   ❌ Error al habilitar usuario en Samba.")
                    errores += 1
            else:
                # Verificar si existe en Samba antes de intentar deshabilitar
                ok_check = ejecutar(f"pdbedit -L -u {username} >/dev/null 2>&1", dry_run)
                if dry_run or ok_check:
                    ok_smb = ejecutar(f"smbpasswd -d {username}", dry_run)
                    if not ok_smb:
                        log.error("   ❌ Error al deshabilitar usuario en Samba.")
                        errores += 1
                else:
                    log.info("   ℹ️ El usuario no existe en Samba, se omite deshabilitación.")
                log.warning("   ⚠️ Usuario deshabilitado en Samba (samba_enabled = false). Se revocan todos los accesos de red.")
                # Si está deshabilitado, limpiamos todos sus ACLs y saltamos al siguiente usuario
                limpiar_acls_usuario(username, BASE_DIR, todas_areas, dry_run)
                procesados += 1
                continue

            # ADMIN GLOBAL: acceso total a todo el share
            if role_upper == GLOBAL_ADMIN_ROLE:
                ok = aplicar_acl_base(username, "rwx", BASE_DIR, dry_run)
                log.info(f"   👑 Acceso Global (rwx) → {BASE_DIR}")
                procesados += 1 if ok else 0
                errores += 0 if ok else 1
                continue

            if not carpeta_area:
                log.warning("   ⚠️ Área no definida. Saltando ACLs.")
                errores += 1
                continue

            area_root = f"{BASE_DIR}/{carpeta_area}"
            limpiar_acls_usuario(username, BASE_DIR, todas_areas, dry_run)

            # Calcular áreas a las que el usuario tiene algún acceso (para aislamiento)
            areas_permitidas = {carpeta_area}
            cursor_rutas.execute(QUERY_RUTAS_USUARIO, (user_id,))
            rutas_usuario = cursor_rutas.fetchall()
            for _, _, area_ext in rutas_usuario:
                if area_ext:
                    areas_permitidas.add(area_ext)

            aplicar_aislamiento_raiz(username, BASE_DIR, todas_areas, areas_permitidas, dry_run)

            # 1. Aplicar permiso de rol sobre el área nativa (Modo Base)
            permisos = PERMISOS_POR_ROL.get(role_upper)
            if not permisos:
                log.warning(f"   ⚠️  Rol '{role_upper}' sin linux_acl en BD. Denegando acceso.")
                permisos = "---"
            else:
                log.info(f"   ℹ️  Modo base (Rol {role_upper}): {permisos} → {area_root}")

            ok_base = aplicar_acl_base(username, permisos, area_root, dry_run)
            log.info(f"   {icono_acl(permisos)} Permisos base aplicados: {permisos} → {area_root}")

            # 2. Aplicar rutas granulares (excepciones / accesos extra)
            ok_granular = True
            if rutas_usuario:
                log.info(f"   🗂️  {len(rutas_usuario)} excepción(es) o ruta(s) extra detectadas")
                ok_granular = aplicar_acl_granular(username, rutas_usuario, carpeta_area, dry_run)

            if ok_base and ok_granular:
                procesados += 1
            else:
                log.error("   ❌ Error al aplicar setfacl en ACLs Base o Granulares.")
                errores += 1

        cursor_usuarios.close()
        cursor_rutas.close()
        conn.close()

        log.info("═══════════════════════════════════════")
        log.info("🚀 Fin de la operación.")
        log.info(f"   ✅ Exitosos : {procesados}")
        log.info(f"   ❌ Fallidos  : {errores}")

    except psycopg2.OperationalError as e:
        log.error(f"❌ Error de conexión a PostgreSQL: {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"❌ Error crítico: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sincronizador de Usuarios y Permisos Samba")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin aplicar cambios")
    parser.add_argument("--user-id", type=int, default=None, help="Sincronizar solo a un usuario específico")
    args = parser.parse_args()

    sincronizar_samba(dry_run=args.dry_run, target_user_id=args.user_id)