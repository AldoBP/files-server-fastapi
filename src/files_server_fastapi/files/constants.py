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


# ── OnlyOffice ────────────────────────────────────────────────────────────────
# ONLYOFFICE_MODE:
#   "desktop" → el usuario descarga el archivo y lo abre con OnlyOffice instalado localmente.
#               No requiere Document Server. Modo de pruebas/desarrollo.
#   "server"  → integración completa con un OnlyOffice Document Server desplegado.
#               Requiere ONLYOFFICE_SERVER_URL y ONLYOFFICE_JWT_SECRET configurados.
ONLYOFFICE_MODE: str = os.getenv("ONLYOFFICE_MODE", "desktop")

# URL del OnlyOffice Document Server (solo requerida en modo "server")
# Ejemplo: "https://onlyoffice.miempresa.com"
ONLYOFFICE_SERVER_URL: str = os.getenv("ONLYOFFICE_SERVER_URL", "")

# Secret JWT para firmar tokens hacia el Document Server (solo modo "server")
ONLYOFFICE_JWT_SECRET: str = os.getenv("ONLYOFFICE_JWT_SECRET", "")

# URL base pública del FastAPI para que el Document Server pueda llamar al callback
# Ejemplo: "https://api.miempresa.com"
ONLYOFFICE_CALLBACK_BASE_URL: str = os.getenv("ONLYOFFICE_CALLBACK_BASE_URL", "")

# Extensiones que OnlyOffice puede abrir (reemplaza a OFFICE_PROTOCOLS)
# El frontend usará esto para decidir si mostrar el botón "Abrir en OnlyOffice"
ONLYOFFICE_SUPPORTED_EXTS: frozenset[str] = frozenset({
    # Documentos de texto
    "doc", "docx", "dot", "dotx", "odt", "rtf", "txt",
    # Hojas de cálculo
    "xls", "xlsx", "xlsm", "ods", "csv",
    # Presentaciones
    "ppt", "pptx", "pps", "ppsx", "odp",
})

# MIME types que el navegador puede mostrar inline (sin descarga forzada)
INLINE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "text/plain", "text/csv", "text/html",
}
