"""
OnlyOffice Router
=================
Gestiona la apertura y edición de archivos Office mediante OnlyOffice.

Modos de operación (configurado en .env con ONLYOFFICE_MODE):
  - "desktop": El archivo se descarga y el usuario lo abre con OnlyOffice instalado
               en su máquina. No requiere Document Server. Modo de pruebas/desarrollo.
  - "server":  Integración completa con OnlyOffice Document Server.
               Requiere ONLYOFFICE_SERVER_URL y ONLYOFFICE_JWT_SECRET configurados.
               El editor se embebe directamente en la interfaz web.

Para pasar de modo "desktop" a "server", solo cambia ONLYOFFICE_MODE=server en .env
y configura las otras variables ONLYOFFICE_* necesarias.
"""
import os
import json
import hmac
import hashlib
import httpx
from functools import partial

from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pgsqlasync2fast_fastapi import get_db_session
from oauth2fast_fastapi import User
from oauth2fast_fastapi.utils.token_utils import verify_token
from sqlmodel import select

from files_server_fastapi.files.constants import (
    BASE_DIR,
    ONLYOFFICE_MODE,
    ONLYOFFICE_SERVER_URL,
    ONLYOFFICE_JWT_SECRET,
    ONLYOFFICE_CALLBACK_BASE_URL,
    ONLYOFFICE_SUPPORTED_EXTS,
)
from files_server_fastapi.files.dependencies import (
    check_folder_access,
    can_edit,
    can_upload,
    resolve_effective_access,
    _resolve_user_context,
)

router = APIRouter()

# Usa la conexión "auth" igual que oauth2fast_fastapi internamente
get_auth_session = partial(get_db_session, connection_name="auth")

# ── Mapeo extensión → tipo de documento OnlyOffice ────────────────────────────
_EXT_TO_DOCTYPE: dict[str, str] = {
    # Documentos de texto → "word"
    "doc":  "word", "docx": "word", "dot": "word", "dotx": "word",
    "odt":  "word", "rtf":  "word", "txt": "word",
    # Hojas de cálculo → "cell"
    "xls":  "cell", "xlsx": "cell", "xlsm": "cell", "ods": "cell", "csv": "cell",
    # Presentaciones → "slide"
    "ppt":  "slide", "pptx": "slide", "pps": "slide", "ppsx": "slide", "odp": "slide",
}


def _build_onlyoffice_jwt(payload: dict) -> str:
    """
    Genera un JWT firmado con ONLYOFFICE_JWT_SECRET para autenticar
    la configuración enviada al Document Server (solo modo 'server').
    """
    import base64
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()
    signature = hmac.new(
        ONLYOFFICE_JWT_SECRET.encode(),
        f"{header}.{body}".encode(),
        hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{body}.{sig_b64}"


async def _authenticate_request(
    request: Request,
    token: str | None,
    auth_session: AsyncSession,
) -> User:
    """
    Autentica la petición aceptando el JWT de dos formas:
      1. Query param ?token=<jwt>  (para pestañas nuevas / window.open)
      2. Header Authorization: Bearer <jwt>  (uso normal de API)

    Lanza 401 si no hay token o es inválido.
    """
    raw_token = token
    if not raw_token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:]

    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se proporcionó token de autenticación",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_token(raw_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email: str | None = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin usuario")

    result = await auth_session.execute(select(User).where(User.email == email))
    current_user = result.scalar_one_or_none()
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    return current_user


@router.get(
    "/onlyoffice/open",
    summary="Abrir un archivo con OnlyOffice (modo lectura o edición según permiso)",
)
async def onlyoffice_open(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    token: str = Query(None, description="JWT token (alternativa al header Authorization, necesario al abrir en nueva pestaña)"),
    auth_session: AsyncSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Genera la información necesaria para que el frontend abra un archivo con OnlyOffice.

    Acepta el token JWT de **dos formas**:
    - Header `Authorization: Bearer <token>` (uso normal en API)
    - Query param `?token=<token>` (necesario cuando se abre en nueva pestaña,
      ya que el navegador no envía headers personalizados en `window.open()`)

    ### Permisos:
    - **web_view**: Abre en modo **solo lectura**. No puede editar ni guardar.
    - **web_edit** y superiores: Abre en modo **edición**. Los cambios se guardan automáticamente.

    ### Modo Desktop (ONLYOFFICE_MODE=desktop):
    Retorna una URL de descarga para que el usuario abra el archivo con OnlyOffice instalado
    en su máquina. Útil para pruebas sin necesidad de un Document Server.

    ### Modo Server (ONLYOFFICE_MODE=server):
    Retorna la configuración JSON completa para inicializar el editor OnlyOffice embebido
    en la interfaz web con el SDK de OnlyOffice.
    """
    # ── 1. Autenticación (acepta token por query param o por header) ─────────
    current_user = await _authenticate_request(request, token, auth_session)

    if ".." in subpath or ".." in filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    # ── 2. Autorización: resolver permiso efectivo del usuario ───────────────
    is_super_admin, user_ext_in_area = await _resolve_user_context(current_user, area, db)
    effective = await resolve_effective_access(
        area=area,
        subpath=subpath,
        user_id=current_user.id,
        user_ext_in_area=user_ext_in_area,
        is_super_admin=is_super_admin,
        db=db,
    )

    if not effective or effective == "deny_all":
        raise HTTPException(status_code=403, detail="Acceso denegado a esta ruta.")

    # ── 3. Validar archivo ───────────────────────────────────────────────────
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
    if ext not in ONLYOFFICE_SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"El tipo de archivo '.{ext}' no es soportado por OnlyOffice.",
        )

    doc_type = _EXT_TO_DOCTYPE.get(ext, "word")
    user_can_edit = can_edit(effective)
    user_can_download = can_upload(effective)

    # ── Modo Desktop ─────────────────────────────────────────────────────────
    if ONLYOFFICE_MODE == "desktop":
        return {
            "mode": "desktop",
            "filename": safe_filename,
            "ext": ext,
            "doc_type": doc_type,
            "can_edit": user_can_edit,
            "can_download": user_can_download,
            "download_url": (
                f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}"
            ),
            "message": (
                "Descarga el archivo y ábrelo con OnlyOffice instalado en tu equipo."
                if user_can_edit
                else "Descarga el archivo para visualizarlo. Solo tienes permiso de lectura."
            ),
        }

    # ── Modo Server ───────────────────────────────────────────────────────────
    doc_key = hashlib.md5(
        f"{area}/{safe_subpath}/{safe_filename}/{os.path.getmtime(ruta_real)}".encode()
    ).hexdigest()

    document_url = (
        f"{ONLYOFFICE_CALLBACK_BASE_URL}/files/view"
        f"?area={area}&subpath={subpath}&filename={safe_filename}"
    )
    callback_url = (
        f"{ONLYOFFICE_CALLBACK_BASE_URL}/files/onlyoffice/callback"
        f"?area={area}&subpath={subpath}&filename={safe_filename}"
    )

    config = {
        "document": {
            "fileType": ext,
            "key": doc_key,
            "title": safe_filename,
            "url": document_url,
            "permissions": {
                "comment":        user_can_edit,
                "download":       user_can_download,
                "edit":           user_can_edit,
                "print":          user_can_download,
                "review":         user_can_edit,
                "fillForms":      user_can_edit,
                "modifyFilter":   user_can_edit,
                "modifyContentControl": user_can_edit,
                "copy":           user_can_edit,
                "protect":        False,
            },
        },
        "documentType": doc_type,
        "editorConfig": {
            "callbackUrl": callback_url if user_can_edit else "",
            "lang": "es",
            "mode": "edit" if user_can_edit else "view",
            "user": {
                "id": str(current_user.id),
                "name": getattr(current_user, "username", str(current_user.id)),
            },
        },
    }

    if ONLYOFFICE_JWT_SECRET:
        config["token"] = _build_onlyoffice_jwt(config)

    return {
        "mode": "server",
        "document_server_url": ONLYOFFICE_SERVER_URL,
        "filename": safe_filename,
        "ext": ext,
        "doc_type": doc_type,
        "can_edit": user_can_edit,
        "can_download": user_can_download,
        "config": config,
    }


@router.post(
    "/onlyoffice/callback",
    summary="Callback de OnlyOffice Document Server para guardar cambios",
    include_in_schema=True,
)
async def onlyoffice_callback(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Endpoint llamado automáticamente por el OnlyOffice Document Server cuando
    un usuario guarda cambios en un documento.

    El Document Server hace POST con un JSON que incluye el estado de guardado
    y la URL del archivo modificado. Este endpoint descarga el archivo y lo
    sobreescribe en BASE_DIR.

    Solo relevante en ONLYOFFICE_MODE=server.

    Referencia: https://api.onlyoffice.com/editors/callback
    """
    if ONLYOFFICE_MODE == "desktop":
        return JSONResponse({"error": 0})

    body = await request.json()
    status_code = body.get("status")

    # Status 2 = documento listo para guardar
    # Status 6 = documento guardado con errores
    # Otros status (1=editando, 3=error, 4=sin cambios, etc.) → no hacer nada
    if status_code not in (2, 6):
        return JSONResponse({"error": 0})

    download_url = body.get("url")
    if not download_url:
        return JSONResponse({"error": 1, "message": "No se recibió URL del documento guardado"})

    safe_filename = os.path.basename(filename)
    safe_subpath = subpath.strip("/")
    ruta_destino = (
        os.path.join(BASE_DIR, area.upper(), safe_subpath, safe_filename)
        if safe_subpath
        else os.path.join(BASE_DIR, area.upper(), safe_filename)
    )

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            with open(ruta_destino, "wb") as f:
                f.write(resp.content)
    except Exception as e:
        return JSONResponse({"error": 1, "message": f"Error al guardar el archivo: {e}"})

    return JSONResponse({"error": 0})
