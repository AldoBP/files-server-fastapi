from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.dependencies.user_dependencies import get_active_user, require_superadmin

router = APIRouter(prefix="/rutas", tags=["Gestión de Rutas"])

@router.post("/", response_model=Rutas, summary="Registrar una Ruta")
async def create_ruta(ruta: Rutas, auth: tuple = Depends(require_superadmin), db: AsyncSession = Depends(get_db_session)):
    db.add(ruta)
    await db.commit()
    await db.refresh(ruta)
    return ruta

@router.get("/", response_model=list[Rutas], summary="Obtener todas las Rutas")
async def get_rutas(auth=Depends(get_active_user), db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Rutas))
    return result.scalars().all()
