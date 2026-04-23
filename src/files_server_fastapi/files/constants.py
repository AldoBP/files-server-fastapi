import os
import re as _re
from dotenv import load_dotenv

load_dotenv()

# Directorio maestro (ruta local en servidor Linux)
BASE_DIR = os.getenv("FILES_BASE_DIR")
# Directorio compartido para clientes Windows (Samba UNC Path) — ej: \\192.168.1.10\samba
SMB_BASE_DIR = os.getenv("SMB_BASE_DIR")

# Desglose de SMB_BASE_DIR para construir URLs smb:// (LibreOffice Linux/Mac)
# Ejemplo: SMB_BASE_DIR = "\\\\192.168.1.10\\samba"  →  SMB_HOST = "192.168.1.10", SMB_SHARE_NAME = "samba"
_smb_match = _re.match(r"^\\\\([^\\/]+)\\(.+)", SMB_BASE_DIR or "")
SMB_HOST: str = _smb_match.group(1) if _smb_match else ""
SMB_SHARE_NAME: str = _smb_match.group(2) if _smb_match else ""


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
