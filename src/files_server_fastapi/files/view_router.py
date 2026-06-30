import os
import mimetypes
from functools import partial

from fastapi import APIRouter, HTTPException, Request, Depends, Query, status
from fastapi.responses import FileResponse
from pgsqlasync2fast_fastapi import get_db_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from oauth2fast_fastapi.models.user_model import User
from oauth2fast_fastapi.utils.token_utils import verify_token
from files_server_fastapi.files.constants import BASE_DIR, INLINE_MIME_TYPES
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.files.media_token import verify_media_token

router = APIRouter()

# Usa la conexión "auth" igual que oauth2fast_fastapi internamente
get_auth_session = partial(get_db_session, connection_name="auth")
# Conexión principal de la aplicación (para check_folder_access)
get_files_session = get_db_session


@router.get("/view", summary="Visualizar un archivo inline en el navegador")
async def view_file_inline(
    request: Request,
    area: str,
    filename: str,
    subpath: str = "/",
    media_token: str = Query(None, description="Media token HMAC de corta vida (para <img src> y links directos)"),
    auth_session: AsyncSession = Depends(get_auth_session),
    db: AsyncSession = Depends(get_files_session),
):
    """
    Sirve archivos visualizables (imágenes, PDF, texto) directamente en el navegador.

    Acepta autenticación de dos formas mutuamente excluyentes:

    1. **`?media_token=<hmac>`** (recomendado para `<img src>` y links directos):
       Token HMAC de corta vida generado por `/files/open-url`. No expone el JWT
       de sesión en la URL. Caduca en `MEDIA_TOKEN_TTL_SECONDS` segundos (default: 10 min).

    2. **Header `Authorization: Bearer <jwt>`** (para llamadas directas a la API):
       Flujo estándar con verificación completa de JWT y ACLs.

    Solo funciona con tipos de archivo que el navegador puede mostrar inline.
    """
    # ── Validación de ruta ANTES de cualquier autenticación ─────────────────
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

    # ── Autenticación: media_token (vía URL) o header Authorization ─────────
    if media_token:
        # Flujo 1: media token HMAC (para <img src>, links directos)
        # El token ya encode area+subpath+filename+user_id+expiry firmados.
        # Si la firma es válida y el token no ha expirado, el acceso ya fue
        # verificado en /open-url cuando se generó el token.
        user_id = verify_media_token(
            media_token,
            area=area,
            subpath=subpath,
            filename=safe_filename,
        )
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Media token inválido o expirado. Recarga la página para obtener uno nuevo.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Token válido — se salta la verificación de ACL (ya fue hecha al generar el token)
    else:
        # Flujo 2: JWT de sesión por header Authorization
        raw_token: str | None = None
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

        # Verificar permiso sobre la ruta (RBAC jerárquico)
        await check_folder_access(
            area=area,
            subpath=subpath,
            required_access="view",
            current_user=current_user,
            db=db,
        )

    # ── 4. Solo tipos visualizables ─────────────────────────────────────────────
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
            "X-Content-Type-Options": "nosniff",
        },
    )
