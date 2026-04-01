from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.permisos_model import Permisos, User_Ruta_Access, Permiso_rol

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

@router.put("/{permiso_id}", response_model=Permisos, summary="Editar Permiso Maestro")
async def update_permiso(permiso_id: int, permiso_data: Permisos, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permisos).where(Permisos.id == permiso_id))
    db_permiso = result.scalars().first()
    if not db_permiso:
        return {"detail": "Permiso no encontrado"}
    
    db_permiso.permiso_name = permiso_data.permiso_name
    db_permiso.description = permiso_data.description
    
    await db.commit()
    await db.refresh(db_permiso)
    return db_permiso

@router.delete("/{permiso_id}", summary="Eliminar Permiso Maestro")
async def delete_permiso(permiso_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permisos).where(Permisos.id == permiso_id))
    db_permiso = result.scalars().first()
    if not db_permiso:
        return {"detail": "Permiso no encontrado"}
    
    await db.delete(db_permiso)
    await db.commit()
    return {"message": "Permiso maestro eliminado"}

# --- Asignaciones Intermedias ---
@router.post("/asignar-acl", response_model=User_Ruta_Access, summary="Asignar o Denegar acceso a ruta (ACL)")
async def assign_acl(acl: User_Ruta_Access, db: AsyncSession = Depends(get_db_session)):
    db.add(acl)
    await db.commit()
    await db.refresh(acl)
    return acl

@router.post("/asignar-rol", response_model=Permiso_rol, summary="Asignar permiso a un Rol")
async def assign_rol(permiso: Permiso_rol, db: AsyncSession = Depends(get_db_session)):
    db.add(permiso)
    await db.commit()
    await db.refresh(permiso)
    return permiso

@router.get("/asignaciones-rol", summary="Ver todas las asignaciones de Permisos a Roles")
async def get_asignaciones_rol(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permiso_rol))
    return result.scalars().all()

@router.delete("/asignar-rol/{asignacion_id}", summary="Revocar permiso a un Rol")
async def revoke_rol_permission(asignacion_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permiso_rol).where(Permiso_rol.id == asignacion_id))
    db_asig = result.scalars().first()
    if not db_asig:
        return {"detail": "Asignación no encontrada"}
    
    await db.delete(db_asig)
    await db.commit()
    return {"message": "Permiso revocado del rol"}
