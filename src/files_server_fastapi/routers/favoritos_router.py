"""
routers/favoritos_router.py
============================
Gestión de Accesos Directos / Favoritos de carpetas por usuario.

Endpoints:
    GET  /favoritos/          → Lista los favoritos del usuario autenticado
    POST /favoritos/          → Agrega un acceso directo a una carpeta
    PUT  /favoritos/{id}      → Edita alias u orden de un favorito
    DELETE /favoritos/{id}    → Elimina un acceso directo

Seguridad:
    - Cualquier usuario activo puede gestionar SUS propios favoritos.
    - Un usuario solo puede ver/editar/borrar sus propios registros.
    - Al crear, se valida que la ruta pertenezca al área del usuario
      o que tenga un acceso explícito (user_ruta_access) para ella,
      impidiendo que alguien agregue como favorito una carpeta ajena.
    - Un superadmin puede agregar cualquier ruta sin restricción de área.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User

from files_server_fastapi.models.favoritos_model import UserFavorito
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.rol_model import Rol
from files_server_fastapi.dependencies.user_dependencies import (
    get_active_user,
    PRIVILEGE_SUPERADMIN,
)

router = APIRouter(prefix="/favoritos", tags=["Accesos Directos"])


# ── Schemas de entrada ────────────────────────────────────────────────────────

class FavoritoCreate(BaseModel):
    """Datos necesarios para crear un acceso directo."""
    ruta_id: int
    alias: Optional[str] = None
    orden: int = 0


class FavoritoUpdate(BaseModel):
    """Campos editables de un acceso directo existente."""
    alias: Optional[str] = None
    orden: Optional[int] = None


# ── Schema de respuesta enriquecida ───────────────────────────────────────────

class FavoritoResponse(BaseModel):
    """Favorito con información de la ruta para que el frontend pueda navegar."""
    id: int
    user_id: int
    ruta_id: int
    alias: Optional[str]
    orden: int
    # Datos de la ruta resueltos en el servidor
    ruta_path: str          # Ruta real en el sistema de archivos
    ruta_name: str          # Nombre original de la carpeta
    area_id: int            # Área a la que pertenece la ruta

    class Config:
        from_attributes = True


# ── Helper interno ────────────────────────────────────────────────────────────

async def _get_user_ext_and_level(user_id: int, db: AsyncSession) -> tuple[Users_extend, int]:
    """Retorna (Users_extend, privilege_level) del usuario. Lanza 403 si no existe."""
    result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_id))
    ext = result.scalars().first()
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene datos de extensión registrados.",
        )
    rol_result = await db.execute(select(Rol).where(Rol.id == ext.rol_id))
    rol = rol_result.scalars().first()
    level = rol.privilege_level if rol else 0
    return ext, level


async def _build_response(fav: UserFavorito, ruta: Rutas) -> FavoritoResponse:
    return FavoritoResponse(
        id=fav.id,
        user_id=fav.user_id,
        ruta_id=fav.ruta_id,
        alias=fav.alias,
        orden=fav.orden,
        ruta_path=ruta.ruta,
        ruta_name=ruta.name,
        area_id=ruta.area_id,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get(
    "/",
    response_model=list[FavoritoResponse],
    summary="Ver mis accesos directos",
    description=(
        "Retorna todos los favoritos del usuario autenticado, "
        "ordenados por el campo `orden` (ascendente)."
    ),
)
async def get_favoritos(
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(UserFavorito)
        .where(UserFavorito.user_id == current_user.id)
        .order_by(UserFavorito.orden)
    )
    favs = result.scalars().all()

    respuestas = []
    for fav in favs:
        ruta_result = await db.execute(select(Rutas).where(Rutas.id == fav.ruta_id))
        ruta = ruta_result.scalars().first()
        if ruta:
            respuestas.append(await _build_response(fav, ruta))

    return respuestas


@router.post(
    "/",
    response_model=FavoritoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Agregar acceso directo a una carpeta",
    description=(
        "Crea un nuevo acceso directo hacia una carpeta. "
        "El usuario solo puede agregar carpetas de su propia área "
        "o sobre las que tenga acceso explícito. "
        "Los superadmin pueden agregar cualquier ruta."
    ),
)
async def create_favorito(
    data: FavoritoCreate,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    # 1. Obtener datos del usuario (área y nivel de privilegio)
    ext, level = await _get_user_ext_and_level(current_user.id, db)

    # 2. Verificar que la ruta existe
    ruta_result = await db.execute(select(Rutas).where(Rutas.id == data.ruta_id))
    ruta = ruta_result.scalars().first()
    if not ruta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La carpeta con id={data.ruta_id} no existe.",
        )

    # 3. Verificar acceso: superadmin tiene libre paso,
    #    los demás deben tener la ruta en su área o un acceso explícito.
    if level < PRIVILEGE_SUPERADMIN:
        tiene_acceso = ruta.area_id == ext.area_id

        if not tiene_acceso:
            # Revisar si tiene acceso explícito via user_ruta_access
            acl_result = await db.execute(
                select(User_Ruta_Access).where(
                    User_Ruta_Access.user_id == current_user.id,
                    User_Ruta_Access.ruta_id == data.ruta_id,
                )
            )
            acl = acl_result.scalars().first()
            if not acl or acl.access_type == "deny_all":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No tienes acceso a esta carpeta para agregarla como favorito.",
                )

    # 4. Evitar duplicados: el mismo usuario no puede agregar la misma ruta dos veces
    dup_result = await db.execute(
        select(UserFavorito).where(
            UserFavorito.user_id == current_user.id,
            UserFavorito.ruta_id == data.ruta_id,
        )
    )
    if dup_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta carpeta ya está en tus accesos directos.",
        )

    # 5. Crear el favorito
    nuevo = UserFavorito(
        user_id=current_user.id,
        ruta_id=data.ruta_id,
        alias=data.alias,
        orden=data.orden,
    )
    db.add(nuevo)
    await db.commit()
    await db.refresh(nuevo)

    return await _build_response(nuevo, ruta)


@router.put(
    "/{favorito_id}",
    response_model=FavoritoResponse,
    summary="Editar alias u orden de un acceso directo",
)
async def update_favorito(
    favorito_id: int,
    data: FavoritoUpdate,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    # Buscar el favorito y verificar que pertenece al usuario actual
    result = await db.execute(
        select(UserFavorito).where(
            UserFavorito.id == favorito_id,
            UserFavorito.user_id == current_user.id,
        )
    )
    fav = result.scalars().first()
    if not fav:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Acceso directo no encontrado o no te pertenece.",
        )

    # Aplicar cambios
    if data.alias is not None:
        fav.alias = data.alias
    if data.orden is not None:
        fav.orden = data.orden

    await db.commit()
    await db.refresh(fav)

    ruta_result = await db.execute(select(Rutas).where(Rutas.id == fav.ruta_id))
    ruta = ruta_result.scalars().first()

    return await _build_response(fav, ruta)


@router.delete(
    "/{favorito_id}",
    status_code=status.HTTP_200_OK,
    summary="Eliminar un acceso directo",
)
async def delete_favorito(
    favorito_id: int,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(UserFavorito).where(
            UserFavorito.id == favorito_id,
            UserFavorito.user_id == current_user.id,
        )
    )
    fav = result.scalars().first()
    if not fav:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Acceso directo no encontrado o no te pertenece.",
        )

    await db.delete(fav)
    await db.commit()
    return {"message": "Acceso directo eliminado correctamente."}
