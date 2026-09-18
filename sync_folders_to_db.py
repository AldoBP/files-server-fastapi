#!/usr/bin/env python3
"""
sync_folders_to_db.py — Sincronizador de Sistema de Archivos a BD (Inverso)
===========================================================================
Escanea el sistema de archivos físico (Samba) y sincroniza las carpetas
faltantes en la tabla `rutas` de PostgreSQL.
"""

import os
import sys
import logging
import psycopg2
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)

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

BASE_DIR = os.getenv("FILES_BASE_DIR",
           os.getenv("SYNC_BASE_DIR", "/srv/samba_data"))

LOG_FILE = os.getenv("SYNC_FS_LOG_FILE", "/var/log/sync_folders.log")

# Validar permisos de log, sino escribir a /tmp
if not os.access(os.path.dirname(LOG_FILE), os.W_OK):
    LOG_FILE = "/tmp/sync_folders.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def sincronizar_fs_a_db(dry_run: bool = False):
    modo = "DRY-RUN" if dry_run else "PRODUCCIÓN"
    log.info("═══════════════════════════════════════")
    log.info(f"🔄 Iniciando sincronización de FS a BD — Modo: {modo}")
    log.info("═══════════════════════════════════════")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        cursor = conn.cursor()

        # 1. Cargar áreas
        cursor.execute("SELECT id, UPPER(TRIM(area_name)) FROM area;")
        areas_db = {row[1]: row[0] for row in cursor.fetchall()}
        log.info(f"🗺️  Áreas en BD: {len(areas_db)}")

        # 2. Cargar rutas existentes
        cursor.execute("SELECT id, ruta FROM rutas;")
        rutas_db = {row[1]: row[0] for row in cursor.fetchall()}
        log.info(f"📁 Rutas registradas en BD: {len(rutas_db)}")

        # 3. Escanear disco
        if not os.path.exists(BASE_DIR):
            log.error(f"❌ El directorio base {BASE_DIR} no existe. Configura FILES_BASE_DIR correctamente.")
            sys.exit(1)

        nuevas_rutas = 0

        # os.walk es top-down
        for root, dirs, files in os.walk(BASE_DIR):
            rel_path = os.path.relpath(root, BASE_DIR)
            if rel_path == ".":
                continue

            rel_path = rel_path.replace("\\", "/")
            partes = rel_path.split("/")
            area_name = partes[0].upper()

            if area_name not in areas_db:
                continue

            if len(partes) == 1:
                # Es la raíz del área (ej. "SISTEMAS"), no va en la tabla 'rutas'
                continue

            logical_path = rel_path
            folder_name = partes[-1]
            area_id = areas_db[area_name]

            if logical_path not in rutas_db:
                parent_path = "/".join(partes[:-1])
                ruta_id = None
                if len(partes) > 2:
                    ruta_id = rutas_db.get(parent_path)

                log.info(f"   ✨ Nueva carpeta detectada: {logical_path}")

                if not dry_run:
                    cursor.execute(
                        "INSERT INTO rutas (ruta, name, area_id, ruta_id, created_at, updated_at) VALUES (%s, %s, %s, %s, NOW(), NOW()) RETURNING id;",
                        (logical_path, folder_name, area_id, ruta_id)
                    )
                    nuevo_id = cursor.fetchone()[0]
                    rutas_db[logical_path] = nuevo_id

                nuevas_rutas += 1

        if not dry_run:
            conn.commit()
            log.info("💾 Cambios guardados en BD.")
        else:
            log.info("⚠️ Modo DRY-RUN. No se guardaron los cambios.")

        cursor.close()
        conn.close()

        log.info("═══════════════════════════════════════")
        log.info("🚀 Fin de la sincronización FS -> DB.")
        log.info(f"   ✅ Nuevas rutas detectadas : {nuevas_rutas}")

    except psycopg2.OperationalError as e:
        log.error(f"❌ Error de conexión a PostgreSQL: {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"❌ Error crítico: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    sincronizar_fs_a_db(dry_run="--dry-run" in sys.argv)