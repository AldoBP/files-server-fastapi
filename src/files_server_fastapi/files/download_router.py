import os
import mimetypes
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from files_server_fastapi.files.constants import BASE_DIR, INLINE_MIME_TYPES
from files_server_fastapi.files.dependencies import check_folder_access, VIEW_ONLY_ACCESS_TYPES

router = APIRouter()


@router.get("/download", summary="Descargar o visualizar un archivo inline en el navegador")
async def download_file(
    area: str,
    filename: str,
    subpath: str = "/",
    access_type: str = Depends(check_folder_access),
):
    """
    Sirve un archivo desde el share Samba.

    - PDFs e imágenes → inline en el navegador.
    - Otros tipos → descarga forzada.
    - Usuarios con permiso VIEW_ONLY (allow_view / allow_view_root) → 403.
    """
    # Bloquear descarga para usuarios con permiso de solo visualización
    if access_type in VIEW_ONLY_ACCESS_TYPES:
        raise HTTPException(
            status_code=403,
            detail=(
                "No tienes permiso para descargar este archivo. "
                "Tu acceso es de solo visualización. Usa el visor en línea."
            ),
        )

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

    mime_type, _ = mimetypes.guess_type(safe_filename)
    mime_type = mime_type or "application/octet-stream"
    disposition = "inline" if mime_type in INLINE_MIME_TYPES else "attachment"

    return FileResponse(
        path=ruta_real,
        media_type=mime_type,
        filename=safe_filename,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_filename}"',
            "Cache-Control": "no-cache",
        },
    )
