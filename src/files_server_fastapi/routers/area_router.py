from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.area_model import Area

router = APIRouter(prefix="/areas", tags=["Gestión de Áreas"])

@router.post("/", response_model=Area, summary="Crear una nueva Área")
async def create_area(area: Area, db: AsyncSession = Depends(get_db_session)):
    """
    Guarda una nueva área en la base de datos.
    """
    db.add(area)
    await db.commit()
    await db.refresh(area)
    return area

@router.get("/", response_model=list[Area], summary="Obtener todas las Áreas")
async def get_areas(db: AsyncSession = Depends(get_db_session)):
    """
    Devuelve la lista de todas las áreas registradas.
    """
    result = await db.execute(select(Area))
    return result.scalars().all()
