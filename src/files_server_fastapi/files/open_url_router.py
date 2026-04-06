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
        # ── WebDAV URL (recomendada, funciona desde cualquier lugar) ────────
        # Office abre el archivo via HTTPS/WebDAV, edita en memoria y guarda
        # con PUT directamente al servidor. No se descarga ni re-sube nada.
        # Formato: ms-word:ofe|u|https://servidor/webdav/AREA/subpath/file.docx
        base_url = str(request.base_url).rstrip("/")
        webdav_path_parts = [area.upper()]
        if safe_subpath:
            webdav_path_parts.append(safe_subpath)
        webdav_path_parts.append(safe_filename)
        webdav_path = "/".join(quote(p, safe="") for p in webdav_path_parts)
        webdav_url = f"{base_url}/webdav/{webdav_path}"
        office_url = f"{office_protocol}:ofe|u|{webdav_url}"

        # ── UNC path (alternativa, solo funciona en LAN con Samba montado) ────
        subpath_win = safe_subpath.replace("/", "\\")
        unc_path = (
            f"{SMB_BASE_DIR}\\{area.upper()}\\{subpath_win}\\{safe_filename}"
            if safe_subpath
            else f"{SMB_BASE_DIR}\\{area.upper()}\\{safe_filename}"
        )
        return {
            "type": "office",
            "protocol": office_protocol,
            "url": office_url,        # ← URL principal: WebDAV via HTTP(S)
            "webdav_url": webdav_url, # ← URL WebDAV directa
            "unc_path": unc_path,     # ← Alternativa UNC si el cliente tiene Samba
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
