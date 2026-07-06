from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.rol_model import Rol
from files_server_fastapi.dependencies.user_dependencies import require_superadmin

router = APIRouter(prefix="/roles", tags=["Gestión de Roles"])

@router.post("/", response_model=Rol, summary="Crear un nuevo Rol")
async def create_rol(
    rol: Rol, 
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Crea un nuevo rol en el sistema.
    Solo accesible por Superadmin/Sistemas.
    
    Puedes enviar 'privilege_level' en el cuerpo de la petición:
      0 = Usuario regular
      1 = Admin de Área
      2 = Superadmin/Sistemas
    """
    db.add(rol)
    await db.commit()
    await db.refresh(rol)
    return rol

@router.get("/", response_model=list[Rol], summary="Obtener todos los Roles")
async def get_roles(
    db: AsyncSession = Depends(get_db_session)
):
    """
    Obtiene la lista de todos los roles.
    Público para lectura (necesario para formularios de registro/edición).
    """
    result = await db.execute(select(Rol))
    return result.scalars().all()

@router.put("/{rol_id}", response_model=Rol, summary="Editar un Rol")
async def update_rol(
    rol_id: int, 
    rol_data: Rol, 
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Actualiza un rol existente, incluyendo su nivel de privilegio.
    Solo accesible por Superadmin/Sistemas.
    """
    result = await db.execute(select(Rol).where(Rol.id == rol_id))
    db_rol = result.scalars().first()
    if not db_rol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado"
        )
    
    db_rol.role_name = rol_data.role_name
    db_rol.description = rol_data.description
    db_rol.privilege_level = rol_data.privilege_level # <-- Ahora sí se actualiza desde el Dashboard
    
    await db.commit()
    await db.refresh(db_rol)
    return db_rol

@router.delete("/{rol_id}", summary="Eliminar un Rol")
async def delete_rol(
    rol_id: int, 
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Elimina un rol.
    Solo accesible por Superadmin/Sistemas.
    """
    result = await db.execute(select(Rol).where(Rol.id == rol_id))
    db_rol = result.scalars().first()
    if not db_rol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rol no encontrado"
        )
    
    await db.delete(db_rol)
    await db.commit()
    return {"message": "Rol eliminado correctamente"}

