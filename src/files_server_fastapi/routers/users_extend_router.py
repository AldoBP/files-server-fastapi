from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.users_extend_model import Users_extend

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
        return {"role_id": None, "area_id": None}
    
    return {"role_id": user_ext.rol_id, "area_id": user_ext.area_id}
