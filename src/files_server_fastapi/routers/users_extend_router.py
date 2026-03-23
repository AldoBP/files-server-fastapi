from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.users_extend_model import Users_extend

class UserExtendUpdate(BaseModel):
    area_id: Optional[int] = None
    rol_id: Optional[int] = None
    puesto: Optional[str] = None

router = APIRouter(prefix="/users-extend", tags=["Extensión de Usuarios"])

@router.post("/", response_model=Users_extend, summary="Vincular Usuario con Área y Rol")
async def create_user_extend(user_ext: Users_extend, db: AsyncSession = Depends(get_db_session)):
    db.add(user_ext)
    await db.commit()
    await db.refresh(user_ext)
    return user_ext

@router.get("/", response_model=list[Users_extend], summary="Ver vínculos de usuarios")
async def get_users_extend(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend))
    return result.scalars().all()

@router.get("/by-area/{area_id}", response_model=list[Users_extend], summary="Obtener usuarios de un área")
async def get_users_by_area(area_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend).where(Users_extend.area_id == area_id))
    return result.scalars().all()

# ==========================================
# RUTA: Buscar Rol y Área por user_id
# ==========================================
@router.get("/by-user/{user_id}", summary="Obtener Área y Rol de un Usuario específico")
async def get_user_permissions(user_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_id))
    user_ext = result.scalars().first()
    
    if not user_ext:
        return {"role_id": None, "area_id": None, "puesto": None}
    
    return {"role_id": user_ext.rol_id, "area_id": user_ext.area_id, "puesto": user_ext.puesto}


# ==========================================
# RUTA: Actualizar Extensión de un Usuario
# ==========================================
@router.patch("/{user_id}", response_model=Users_extend, summary="Actualizar datos de extensión de usuario")
async def update_user_extend(user_id: int, user_ext_update: UserExtendUpdate, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_id))
    user_ext = result.scalars().first()
    
    if not user_ext:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado en la extensión")
        
    update_data = user_ext_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user_ext, key, value)
        
    db.add(user_ext)
    await db.commit()
    await db.refresh(user_ext)
    
    return user_ext
