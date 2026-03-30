from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.area_model import Area

router = APIRouter(prefix="/areas", tags=["Gestión de Áreas"])


class AreaCreate(BaseModel):
    area_name: str
    description: Optional[str] = None


class AreaUpdate(BaseModel):
    area_name: Optional[str] = None
    description: Optional[str] = None


# ==========================================
# POST /areas/ — Crear nueva área
# ==========================================
@router.post("/", response_model=Area, status_code=status.HTTP_201_CREATED, summary="Crear una nueva Área")
async def create_area(area_data: AreaCreate, db: AsyncSession = Depends(get_db_session)):
    """
    Crea y guarda una nueva área en la base de datos.
    Solo accesible por superusuarios desde el panel de administración.
    """
    # Verificar si ya existe un área con el mismo nombre
    result = await db.execute(select(Area).where(Area.area_name == area_data.area_name))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un área con el nombre '{area_data.area_name}'."
        )

    new_area = Area(**area_data.model_dump())
    db.add(new_area)
    await db.commit()
    await db.refresh(new_area)
    return new_area


# ==========================================
# GET /areas/ — Listar todas las áreas
# ==========================================
@router.get("/", response_model=list[Area], summary="Obtener todas las Áreas")
async def get_areas(db: AsyncSession = Depends(get_db_session)):
    """
    Devuelve la lista de todas las áreas registradas.
    """
    result = await db.execute(select(Area))
    return result.scalars().all()


# ==========================================
# GET /areas/{area_id} — Obtener área por ID
# ==========================================
@router.get("/{area_id}", response_model=Area, summary="Obtener un Área por ID")
async def get_area(area_id: int, db: AsyncSession = Depends(get_db_session)):
    """
    Devuelve los datos de un área específica por su ID.
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )
    return area


# ==========================================
# PATCH /areas/{area_id} — Actualizar área
# ==========================================
@router.patch("/{area_id}", response_model=Area, summary="Actualizar un Área")
async def update_area(area_id: int, area_update: AreaUpdate, db: AsyncSession = Depends(get_db_session)):
    """
    Actualiza parcialmente los datos de un área existente.
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )

    # Si se quiere cambiar el nombre, verificar que no exista otro con ese nombre
    if area_update.area_name and area_update.area_name != area.area_name:
        dup_result = await db.execute(select(Area).where(Area.area_name == area_update.area_name))
        if dup_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un área con el nombre '{area_update.area_name}'."
            )

    update_data = area_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(area, key, value)

    db.add(area)
    await db.commit()
    await db.refresh(area)
    return area


# ==========================================
# DELETE /areas/{area_id} — Eliminar área
# ==========================================
@router.delete("/{area_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar un Área")
async def delete_area(area_id: int, db: AsyncSession = Depends(get_db_session)):
    """
    Elimina un área por su ID.
    ADVERTENCIA: Solo eliminar si no hay usuarios asociados a esta área.
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )

    await db.delete(area)
    await db.commit()
