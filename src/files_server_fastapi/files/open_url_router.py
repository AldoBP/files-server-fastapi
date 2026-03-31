import os
from fastapi import APIRouter, HTTPException, Depends
from files_server_fastapi.files.constants import BASE_DIR, SMB_BASE_DIR, OFFICE_PROTOCOLS
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


@router.get("/open-url", summary="Obtener URL para abrir un archivo en la app local (Office, etc.)")
async def get_open_url(
    area: str,
    filename: str,
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access)
):
    """
    Devuelve la URL de protocolo adecuada para abrir el archivo directamente
    en la aplicación instalada en la PC del usuario.

    - Archivos **Office** (.docx, .xlsx, .pptx…): URL `ms-word:ofe|u|...` para abrir y guardar directo.
    - **Otros** (PDF, imágenes, txt): URL del endpoint `/files/download` para vista inline.
    """
    if ".." in subpath or ".." in filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    safe_filename = os.path.basename(filename)
    safe_subpath = subpath.strip("/")
    ruta_real = os.path.join(BASE_DIR, area.upper(), safe_subpath, safe_filename) if safe_subpath else os.path.join(BASE_DIR, area.upper(), safe_filename)

    if not os.path.isfile(ruta_real):
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {safe_filename}")

    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else ""
    office_protocol = OFFICE_PROTOCOLS.get(ext)

    if office_protocol:
        subpath_win = safe_subpath.replace("/", "\\")
        unc_path = f"{SMB_BASE_DIR}\\{area.upper()}\\{subpath_win}\\{safe_filename}" if safe_subpath else f"{SMB_BASE_DIR}\\{area.upper()}\\{safe_filename}"
        return {
            "type": "office",
            "protocol": office_protocol,
            "url": f"{office_protocol}:ofe|u|{unc_path}",
            "unc_path": unc_path,
            "filename": safe_filename,
        }

    return {
        "type": "download",
        "url": f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}",
        "filename": safe_filename,
    }
