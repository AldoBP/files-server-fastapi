import os
import mimetypes
from functools import partial

from fastapi import APIRouter, HTTPException, Query, Request, Depends, status
from fastapi.responses import FileResponse
from pgsqlasync2fast_fastapi import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from oauth2fast_fastapi.models.user_model import User
from oauth2fast_fastapi.utils.token_utils import verify_token
from files_server_fastapi.files.constants import BASE_DIR, INLINE_MIME_TYPES

router = APIRouter()

# Usa la conexión "auth" igual que oauth2fast_fastapi internamente
get_auth_session = partial(get_db_session, connection_name="auth")



@router.get("/view", summary="Visualizar un archivo inline en el navegador (token por query param)")
async def view_file_inline(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    token: str = Query(None, description="JWT token (alternativa al header Authorization)"),
    auth_session: AsyncSession = Depends(get_auth_session),
):
    """
    Sirve archivos visualizables (imágenes, PDF, texto) directamente en el navegador.

    Acepta el token JWT de dos formas:
    - Header `Authorization: Bearer <token>` (uso normal en API)
    - Query param `?token=<token>` (para uso en `<img src>`, `window.open`, compartir links)

    Solo funciona con tipos de archivo que el navegador puede mostrar inline.
    """
    # --- Autenticación: query param tiene prioridad, si no, intenta el header ---
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
    if email is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token sin usuario")

    result = await auth_session.execute(select(User).where(User.email == email))
    current_user = result.scalar_one_or_none()
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario no encontrado")

    # --- Validación de ruta ---
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

    # --- Solo tipos visualizables ---
    mime_type, _ = mimetypes.guess_type(safe_filename)
    mime_type = mime_type or "application/octet-stream"

    if mime_type not in INLINE_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo no visualizable. Usa /files/download para '{safe_filename}'.",
        )

    return FileResponse(
        path=ruta_real,
        media_type=mime_type,
        filename=safe_filename,
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )
