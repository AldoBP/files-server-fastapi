# Directorio maestro (ruta de red Samba vista desde Windows)
BASE_DIR = r"\\192.168.1.122\Compartido"

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
