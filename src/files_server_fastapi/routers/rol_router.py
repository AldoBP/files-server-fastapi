from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.rol_model import Rol

router = APIRouter(prefix="/roles", tags=["Gestión de Roles"])

@router.post("/", response_model=Rol, summary="Crear un nuevo Rol")
async def create_rol(rol: Rol, db: AsyncSession = Depends(get_db_session)):
    db.add(rol)
    await db.commit()
    await db.refresh(rol)
    return rol

@router.get("/", response_model=list[Rol], summary="Obtener todos los Roles")
async def get_roles(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Rol))
    return result.scalars().all()
