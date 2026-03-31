import os
from dotenv import load_dotenv

load_dotenv()

# Directorio maestro (ruta local en servidor Linux)
BASE_DIR = os.getenv("FILES_BASE_DIR")
# Directorio compartido para clientes Windows (Samba UNC Path)
SMB_BASE_DIR = os.getenv("SMB_BASE_DIR")


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
