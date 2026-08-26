from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.permisos_model import Permisos, User_Ruta_Access
from files_server_fastapi.dependencies.user_dependencies import get_active_user, require_superadmin

router = APIRouter(prefix="/permisos", tags=["Gestión de Permisos"])

# --- Catálogo Maestro ---
@router.post("/", response_model=Permisos, summary="Crear Permiso Maestro")
async def create_permiso(permiso: Permisos, auth: tuple = Depends(require_superadmin), db: AsyncSession = Depends(get_db_session)):
    db.add(permiso)
    await db.commit()
    await db.refresh(permiso)
    return permiso

@router.get("/", response_model=list[Permisos], summary="Ver Permisos Maestros")
async def get_permisos(auth=Depends(get_active_user), db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permisos))
    return result.scalars().all()

@router.put("/{permiso_id}", response_model=Permisos, summary="Editar Permiso Maestro")
async def update_permiso(permiso_id: int, permiso_data: Permisos, auth: tuple = Depends(require_superadmin), db: AsyncSession = Depends(get_db_session)):
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
async def delete_permiso(permiso_id: int, auth: tuple = Depends(require_superadmin), db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Permisos).where(Permisos.id == permiso_id))
    db_permiso = result.scalars().first()
    if not db_permiso:
        return {"detail": "Permiso no encontrado"}
    
    await db.delete(db_permiso)
    await db.commit()
    return {"message": "Permiso maestro eliminado"}

