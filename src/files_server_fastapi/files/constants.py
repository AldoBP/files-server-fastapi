import os
from dotenv import load_dotenv

load_dotenv()

# Directorio maestro (ruta local en servidor Linux)
BASE_DIR = os.getenv("FILES_BASE_DIR")
# Directorio compartido para clientes Windows (Samba UNC Path)
SMB_BASE_DIR = os.getenv("SMB_BASE_DIR")

# ── WebDAV ────────────────────────────────────────────────────────────────────
# URL de conexión PostgreSQL síncrona (psycopg2) para autenticar usuarios WebDAV.
# Usar postgresql:// (NO postgresql+asyncpg://) — misma BD, distinto driver.
# Ejemplo: postgresql://user:pass@localhost:5432/nombre_bd
WEBDAV_DATABASE_URL = os.getenv("WEBDAV_DATABASE_URL")
# Nombre que verá el usuario en el diálogo de credenciales de Office.
WEBDAV_AUTH_REALM = os.getenv("WEBDAV_AUTH_REALM", "Servidor de Archivos")


# Mapeo extensión → protocolo de Office
OFFICE_PROTOCOLS = {
    "doc":  "ms-word",
    "docx": "ms-word",
    "dot":  "ms-word",
    "dotx": "ms-word",
    "xls":  "ms-excel",
    "xlsx": "ms-excel",
    "xlsm": "ms-excel",
    "ppt":  "ms-powerpoint",
    "pptx": "ms-powerpoint",
    "pps":  "ms-powerpoint",
    "ppsx": "ms-powerpoint",
}

# MIME types que el navegador puede mostrar inline (sin descarga forzada)
INLINE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "text/plain", "text/csv", "text/html",
}
