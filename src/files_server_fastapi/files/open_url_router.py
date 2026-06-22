import os
import mimetypes
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from files_server_fastapi.files.constants import (
    BASE_DIR,
    ONLYOFFICE_SUPPORTED_EXTS,
    INLINE_MIME_TYPES,
)
from files_server_fastapi.files.dependencies import (
    check_folder_access,
    can_view,
    can_edit,
    can_upload,
)

router = APIRouter()

_oauth2 = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)


@router.get(
    "/open-url",
    summary="Obtener opciones de URL para abrir un archivo",
)
async def get_open_url(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    access_type: str = Depends(check_folder_access),
    bearer_token: str = Depends(_oauth2),
):
    """
    Devuelve un array **`options`** con las maneras de abrir el archivo según el permiso del usuario.

    ### Lógica de permisos:
    - **web_view**: Puede ver inline (PDF/imagen) o abrir en OnlyOffice en modo solo lectura.
                   No puede descargar archivos.
    - **web_edit**: Puede ver y abrir en OnlyOffice con edición habilitada. No puede descargar.
    - **web_upload** / **web_full**: Todas las opciones anteriores + opción de descarga.

    ### Archivos de Office (.docx, .xlsx, .pptx, …)
    - Se retorna URL al endpoint `/files/onlyoffice/open` con el modo correspondiente.
    - Modo lectura (`web_view`): OnlyOffice abre el archivo sin permitir edición.
    - Modo edición (`web_edit`+): OnlyOffice permite editar y guardar.

    ### Imágenes / PDF / Texto
    - Opción de ver inline en el navegador.
    - Opción de descarga (solo si tiene `web_upload`+).

    ### Otros archivos
    - Opción de descarga (solo si tiene `web_upload`+).
    - Si no puede descargar: mensaje explicativo.
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
    is_onlyoffice_file = ext in ONLYOFFICE_SUPPORTED_EXTS
    user_can_edit = can_edit(access_type)
    user_can_upload = can_upload(access_type)

    # ── Caso 1: Archivos de Office / OnlyOffice ──────────────────────────────
    if is_onlyoffice_file:
        onlyoffice_url = (
            f"/files/onlyoffice/open?area={area}&subpath={subpath}&filename={safe_filename}"
        )
        if bearer_token:
            onlyoffice_url += f"&token={bearer_token}"

        options = [
            {
                "app": "onlyoffice",
                "label": "Ver en OnlyOffice" if not user_can_edit else "Abrir en OnlyOffice",
                "url": onlyoffice_url,
                "platform": "browser",
                "edit": user_can_edit,
                "hint": (
                    "El archivo se abrirá en el editor OnlyOffice dentro del navegador."
                    if user_can_edit
                    else "El archivo se abrirá en modo solo lectura (sin edición)."
                ),
            }
        ]

        # Permitir también "Ver en el navegador" si el tipo MIME es visualizable (ej. PDF)
        mime_type, _ = mimetypes.guess_type(safe_filename)
        mime_type = mime_type or "application/octet-stream"
        if mime_type in INLINE_MIME_TYPES:
            view_url = f"/files/view?area={area}&subpath={subpath}&filename={safe_filename}"
            if bearer_token:
                view_url += f"&token={bearer_token}"
            options.append({
                "app": "view",
                "label": "Ver en el navegador",
                "url": view_url,
                "platform": "browser",
                "edit": False,
                "hint": "Visualización rápida en el navegador."
            })

        # Descarga solo para web_upload o web_full
        if user_can_upload:
            download_url = f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}"
            if bearer_token:
                download_url += f"&token={bearer_token}"
            
            options.append({
                "app": "download",
                "label": "Descargar",
                "url": download_url,
                "platform": "any",
                "edit": False,
                "hint": "Descarga el archivo para abrirlo localmente.",
            })

        return {
            "filename": safe_filename,
            "ext": ext,
            "is_onlyoffice": True,
            "can_edit": user_can_edit,
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
        ]

        # Descarga solo para web_upload o web_full
        if user_can_upload:
            download_url = f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}"
            if bearer_token:
                download_url += f"&token={bearer_token}"

            options.append({
                "app": "download",
                "label": "Descargar",
                "url": download_url,
                "platform": "any",
                "edit": False,
            })

        return {
            "filename": safe_filename,
            "ext": ext,
            "is_onlyoffice": False,
            "mime_type": mime_type,
            "options": options,
        }

    # ── Caso 3: Resto de archivos ─────────────────────────────────────────────
    if user_can_upload:
        download_url = f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}"
        if bearer_token:
            download_url += f"&token={bearer_token}"
            
        return {
            "filename": safe_filename,
            "ext": ext,
            "is_onlyoffice": False,
            "options": [
                {
                    "app": "download",
                    "label": "Descargar",
                    "url": download_url,
                    "platform": "any",
                    "edit": False,
                }
            ],
        }

    # Sin permiso de descarga
    return {
        "filename": safe_filename,
        "ext": ext,
        "is_onlyoffice": False,
        "options": [],
        "message": (
            "Tu nivel de acceso no permite descargar este tipo de archivo. "
            "Contacta a tu administrador si necesitas acceso adicional."
        ),
    }
