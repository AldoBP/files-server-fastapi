import os
import mimetypes
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from files_server_fastapi.files.constants import BASE_DIR, SMB_BASE_DIR, OFFICE_PROTOCOLS, INLINE_MIME_TYPES
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()

_oauth2 = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


@router.get("/open-url", summary="Obtener URL para abrir un archivo en la app local (Office, etc.)")
async def get_open_url(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access),
    bearer_token: str = Depends(_oauth2),
):
    """
    Devuelve la URL adecuada para abrir el archivo:

    - **Office** (.docx, .xlsx, .pptx…): protocolo `ms-word:ofe|u|...` para edición directa.
    - **Imágenes / PDF / Texto**: URL `/files/view?...&token=<jwt>` para visualizar inline en el navegador
      (incluye el token para que el cliente pueda abrir la URL sin header adicional).
    - **Otros**: URL `/files/download?...` para descarga.
    """
    if ".." in subpath or ".." in filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    safe_filename = os.path.basename(filename)
    safe_subpath = subpath.strip("/")
    ruta_real = (
        os.path.join(BASE_DIR, area.upper(), safe_subpath, safe_filename)
        if safe_subpath
        else os.path.join(BASE_DIR, area.upper(), safe_filename)
    )

    if not os.path.isfile(ruta_real):
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {safe_filename}")

    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else ""
    office_protocol = OFFICE_PROTOCOLS.get(ext)

    # ── Caso 1: Archivos Office ──────────────────────────────────────────────
    if office_protocol:
        # Se genera la ruta UNC para abrir directamente mediante Samba
        subpath_win = safe_subpath.replace("/", "\\")
        unc_path = (
            f"{SMB_BASE_DIR}\\{area.upper()}\\{subpath_win}\\{safe_filename}"
            if safe_subpath
            else f"{SMB_BASE_DIR}\\{area.upper()}\\{safe_filename}"
        )
        return {
            "type": "office",
            "protocol": office_protocol,
            "url": f"{office_protocol}:ofe|u|{unc_path}",
            "unc_path": unc_path,
            "filename": safe_filename,
        }

    # ── Caso 2: Archivos visualizables inline (imágenes, PDF, texto) ─────────
    mime_type, _ = mimetypes.guess_type(safe_filename)
    mime_type = mime_type or "application/octet-stream"

    if mime_type in INLINE_MIME_TYPES:
        view_url = f"/files/view?area={area}&subpath={subpath}&filename={safe_filename}"
        if bearer_token:
            view_url += f"&token={bearer_token}"
        return {
            "type": "view",
            "url": view_url,
            "mime_type": mime_type,
            "filename": safe_filename,
        }

    # ── Caso 3: Resto de archivos → descarga ─────────────────────────────────
    return {
        "type": "download",
        "url": f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}",
        "filename": safe_filename,
    }


from fastapi.responses import PlainTextResponse
import re

@router.get("/samba-trust-script", summary="Descargar script para solucionar error de Vista Protegida de Office")
async def get_samba_trust_script():
    """
    Descarga un script .bat que agrega el servidor Samba a la zona de "Intranet Local"
    en Windows. Esto resuelve el bloqueo 'Vista protegida / Zona Internet' que lanza Office
    cuando se intenta abrir una ruta UNC generada desde el navegador.
    """
    # Extraemos la IP o dominio del servidor de la ruta UNC configurada en .env
    host_match = re.match(r"^\\\\([^\\/]+)", SMB_BASE_DIR)
    host = host_match.group(1) if host_match else "127.0.0.1"

    bat_content = f"""@echo off
echo =========================================================
echo Solucionando bloqueo de Office para el servidor: {host}
echo =========================================================
echo.
echo Agregando {host} a la Intranet Local de Windows...
echo.

:: Agregar configuracion en el Registro usando PowerShell
powershell -Command "$ip = '{host}'; $path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Ranges\\RangeServer'; if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; Set-ItemProperty -Path $path -Name ':Range' -Value $ip; Set-ItemProperty -Path $path -Name 'file' -Value 1;"

echo.
echo [EXITO] Servidor agregado a la zona de confianza.
echo Ahora los archivos de Word/Excel abriran correctamente sin bloqueos.
echo.
pause
"""
    return PlainTextResponse(
        content=bat_content,
        headers={"Content-Disposition": 'attachment; filename="solucion_office_red.bat"'}
    )
