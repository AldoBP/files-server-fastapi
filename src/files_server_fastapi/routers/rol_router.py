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

@router.put("/{rol_id}", response_model=Rol, summary="Editar un Rol")
async def update_rol(rol_id: int, rol_data: Rol, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Rol).where(Rol.id == rol_id))
    db_rol = result.scalars().first()
    if not db_rol:
        return {"detail": "Rol no encontrado"} # Simplified error handling for now
    
    db_rol.role_name = rol_data.role_name
    db_rol.description = rol_data.description
    
    await db.commit()
    await db.refresh(db_rol)
    return db_rol

@router.delete("/{rol_id}", summary="Eliminar un Rol")
async def delete_rol(rol_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Rol).where(Rol.id == rol_id))
    db_rol = result.scalars().first()
    if not db_rol:
        return {"detail": "Rol no encontrado"}
    
    await db.delete(db_rol)
    await db.commit()
    return {"message": "Rol eliminado correctamente"}
