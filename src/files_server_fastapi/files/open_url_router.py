import os
import mimetypes
import re
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import OAuth2PasswordBearer
from files_server_fastapi.files.constants import (
    BASE_DIR,
    SMB_BASE_DIR,
    SMB_HOST,
    SMB_SHARE_NAME,
    OFFICE_PROTOCOLS,
    INLINE_MIME_TYPES,
)
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()

_oauth2 = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


def _build_unc_path(area: str, safe_subpath: str, safe_filename: str) -> str:
    """Construye la ruta UNC de Windows: \\\\servidor\\share\\AREA\\subpath\\archivo"""
    parts = [SMB_BASE_DIR, area.upper()]
    if safe_subpath:
        parts.append(safe_subpath.replace("/", "\\"))
    parts.append(safe_filename)
    return "\\".join(parts)


def _build_smb_url(area: str, safe_subpath: str, safe_filename: str) -> str:
    """Construye la URL smb:// para LibreOffice en Linux/Mac."""
    # smb://host/share/AREA/subpath/archivo
    share = SMB_SHARE_NAME.replace("\\", "/")
    subpath_part = f"/{safe_subpath}" if safe_subpath else ""
    return f"smb://{SMB_HOST}/{share}/{area.upper()}{subpath_part}/{safe_filename}"


@router.get(
    "/open-url",
    summary="Obtener opciones de URL para abrir un archivo (Office, LibreOffice, visor, descarga)",
)
async def get_open_url(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access),
    bearer_token: str = Depends(_oauth2),
):
    """
    Devuelve un array **`options`** con todas las maneras de abrir el archivo.

    Cada opción tiene:
    - `app`: identificador de la aplicación (`ms-office`, `libreoffice-win`,
      `libreoffice-linux`, `view`, `download`).
    - `label`: texto legible para mostrar en el frontend.
    - `url`: la URL o ruta a usar.
    - `platform`: sistema operativo destino (`windows`, `linux`, `any`, `browser`).
    - `edit`: `true` si la opción permite editar y guardar de vuelta al servidor.

    ### Archivos Office (.docx, .xlsx, .pptx, …)
    Se devuelven 4 opciones:
    1. **MS Office (Windows)** — protocolo `ms-word:ofe|u|UNC` para edición directa.
    2. **LibreOffice (Windows)** — ruta UNC directa (`\\\\srv\\share\\...`).
    3. **LibreOffice (Linux/Mac)** — URL `smb://host/share/...`.
    4. **Descargar** — fallback universal.

    ### Imágenes / PDF / Texto
    1. **Ver inline** — `/files/view?...&token=<jwt>`.
    2. **Descargar**.

    ### Otros archivos
    1. **Descargar**.

    ---
    > **Nota para el frontend:** usa `navigator.platform` / `navigator.userAgent`
    > para filtrar `options` por `platform` y mostrar solo las relevantes.
    > Para abrir opciones `ms-office` o `libreoffice-win` usa `window.location.href = url`.
    > Para `libreoffice-linux` muestra la URL con un botón "Copiar".
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
        unc_path = _build_unc_path(area, safe_subpath, safe_filename)
        smb_url = _build_smb_url(area, safe_subpath, safe_filename)

        download_url = (
            f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}"
        )

        options = [
            {
                "app": "ms-office",
                "label": "Microsoft Office (Windows)",
                "url": f"{office_protocol}:ofe|u|{unc_path}",
                "platform": "windows",
                "edit": True,
                "hint": (
                    "Si Office bloquea el archivo por 'Vista Protegida', descarga y ejecuta "
                    "el script en /files/samba-trust-script para agregar el servidor a la "
                    "zona de confianza de Windows."
                ),
            },
            {
                "app": "libreoffice-win",
                "label": "LibreOffice (Windows)",
                "url": unc_path,
                "platform": "windows",
                "edit": True,
                "hint": (
                    "En LibreOffice → Archivo → Abrir, pega esta ruta UNC. "
                    "El archivo se guardará directamente en el servidor."
                ),
            },
            {
                "app": "libreoffice-linux",
                "label": "LibreOffice (Linux / Mac)",
                "url": smb_url,
                "platform": "linux",
                "edit": True,
                "hint": (
                    "En LibreOffice → Archivo → Abrir, pega esta URL smb://. "
                    "El archivo se guardará directamente en el servidor vía Samba."
                ),
            },
            {
                "app": "download",
                "label": "Descargar",
                "url": download_url,
                "platform": "any",
                "edit": False,
                "hint": "Descarga el archivo para abrirlo localmente.",
            },
        ]

        return {
            "filename": safe_filename,
            "ext": ext,
            "is_office": True,
            "unc_path": unc_path,
            "options": options,
        }

    # ── Caso 2: Archivos visualizables inline (imágenes, PDF, texto) ─────────
    mime_type, _ = mimetypes.guess_type(safe_filename)
    mime_type = mime_type or "application/octet-stream"

    if mime_type in INLINE_MIME_TYPES:
        view_url = f"/files/view?area={area}&subpath={subpath}&filename={safe_filename}"
        if bearer_token:
            view_url += f"&token={bearer_token}"

        options = [
            {
                "app": "view",
                "label": "Ver en el navegador",
                "url": view_url,
                "platform": "browser",
                "edit": False,
            },
            {
                "app": "download",
                "label": "Descargar",
                "url": f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}",
                "platform": "any",
                "edit": False,
            },
        ]

        return {
            "filename": safe_filename,
            "ext": ext,
            "is_office": False,
            "mime_type": mime_type,
            "options": options,
        }

    # ── Caso 3: Resto de archivos → solo descarga ────────────────────────────
    return {
        "filename": safe_filename,
        "ext": ext,
        "is_office": False,
        "options": [
            {
                "app": "download",
                "label": "Descargar",
                "url": f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}",
                "platform": "any",
                "edit": False,
            }
        ],
    }


@router.get(
    "/samba-trust-script",
    summary="Descargar script para solucionar error de Vista Protegida de Office",
)
async def get_samba_trust_script():
    """
    Descarga un script `.bat` que agrega el servidor Samba a la zona de "Intranet Local"
    en Windows e instruye a Office a no usar "Vista Protegida" para archivos de red.
    """
    host_match = re.match(r"^\\\\([^\\/]+)", SMB_BASE_DIR or "")
    host = host_match.group(1) if host_match else "127.0.0.1"

    bat_content = f"""@echo off
echo =========================================================
echo Solucionando bloqueo de Office para el servidor: {host}
echo =========================================================
echo.
echo 1. Agregando {host} a la Intranet Local de Windows...
powershell -Command "$ip = '{host}'; $path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Ranges\\RangeServer'; if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; Set-ItemProperty -Path $path -Name ':Range' -Value $ip; Set-ItemProperty -Path $path -Name 'file' -Value 1;"
echo.

echo 2. Desactivando bloqueos de Vista Protegida en Word/Excel para archivos en red...
:: Word
powershell -Command "$path = 'HKCU:\\Software\\Microsoft\\Office\\16.0\\Word\\Security\\ProtectedView'; if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; Set-ItemProperty -Path $path -Name 'DisableUNCLocations' -Value 1 -Type DWord;"
:: Excel
powershell -Command "$path = 'HKCU:\\Software\\Microsoft\\Office\\16.0\\Excel\\Security\\ProtectedView'; if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; Set-ItemProperty -Path $path -Name 'DisableUNCLocations' -Value 1 -Type DWord;"
:: Habilitar red confiable en Office
powershell -Command "$path = 'HKCU:\\Software\\Microsoft\\Office\\16.0\\Common\\Security'; if (!(Test-Path $path)) {{ New-Item -Path $path -Force | Out-Null }}; Set-ItemProperty -Path $path -Name 'DisableAllActiveX' -Value 0 -Type DWord;"
echo.

echo [EXITO] Configuracion aplicada.
echo.
echo IMPORTANTE: Si ya tienes Word o Excel abiertos, debes CERRARLOS y volver
echo a abrirlos para que los cambios surtan efecto.
echo.
pause
"""
    return PlainTextResponse(
        content=bat_content,
        headers={"Content-Disposition": 'attachment; filename="solucion_office_red.bat"'},
    )
