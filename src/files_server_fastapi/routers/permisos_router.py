from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.permisos_model import Permisos, Permiso_user, Permiso_rol

router = APIRouter(prefix="/permisos", tags=["Gestión de Permisos"])

# --- Catálogo Maestro ---
@router.post("/", response_model=Permisos, summary="Crear Permiso Maestro")
async def create_permiso(permiso: Permisos, db: AsyncSession = Depends(get_db_session)):
    db.add(permiso)
    await db.commit()
    await db.refresh(permiso)
    return permiso

@router.get("/", response_model=list[Permisos], summary="Ver Permisos Maestros")
async def get_permisos(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permisos))
    return result.scalars().all()

# --- Asignaciones Intermedias ---
@router.post("/asignar-usuario", response_model=Permiso_user, summary="Asignar permiso a un Usuario")
async def assign_user(permiso: Permiso_user, db: AsyncSession = Depends(get_db_session)):
    db.add(permiso)
    await db.commit()
    await db.refresh(permiso)
    return permiso

@router.post("/asignar-rol", response_model=Permiso_rol, summary="Asignar permiso a un Rol")
async def assign_rol(permiso: Permiso_rol, db: AsyncSession = Depends(get_db_session)):
    db.add(permiso)
    await db.commit()
    await db.refresh(permiso)
    return permiso
