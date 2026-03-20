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

# --- Asignaciones Intermedias ---
@router.post("/asignar-acl", response_model=User_Ruta_Access, summary="Asignar o Denegar acceso a ruta (ACL)")
async def assign_acl(acl: User_Ruta_Access, db: AsyncSession = Depends(get_db_session)):
    """
    Crea una excepción de acceso para un usuario en una ruta específica.
    access_type: "allow_read", "allow_write", "deny_all"
    """
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
