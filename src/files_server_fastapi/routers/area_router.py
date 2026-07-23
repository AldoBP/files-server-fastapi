import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.dependencies.user_dependencies import (
    get_active_user,
    require_superadmin,
    get_current_user_ext,
)
from files_server_fastapi.files.constants import BASE_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/areas", tags=["Gestión de Áreas"])


# ── Schemas ───────────────────────────────────────────────────────────────────

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
async def create_area(
    area_data: AreaCreate,
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Crea y guarda una nueva área en la base de datos.
    Además, crea automáticamente:
      - La carpeta física raíz del área en BASE_DIR/<AREA_NAME>/
      - El registro raíz en la tabla `rutas` para que el área
        aparezca en el explorador de archivos y en Samba.
    Solo accesible por superusuarios desde el panel de administración.
    """
    # Verificar si ya existe un área activa con el mismo nombre
    result = await db.execute(
        select(Area).where(Area.area_name == area_data.area_name, Area.deleted_at.is_(None))
    )
    existing = result.scalars().first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un área activa con el nombre '{area_data.area_name}'."
        )

    # Guardar el área en BD
    new_area = Area(**area_data.model_dump())
    db.add(new_area)
    await db.commit()
    await db.refresh(new_area)

    # ── Crear carpeta física raíz del área ───────────────────────────────────
    folder_name = area_data.area_name.upper()
    ruta_fisica = os.path.join(BASE_DIR, folder_name)
    ruta_logica = folder_name

    try:
        os.makedirs(ruta_fisica, exist_ok=True)
        logger.info("Carpeta raíz del área creada: %s", ruta_fisica)
    except PermissionError:
        logger.error("Sin permiso para crear carpeta del área: %s", ruta_fisica)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"Área creada en BD (id={new_area.id}), pero no se pudo crear "
                f"la carpeta física en '{ruta_fisica}': permiso denegado. "
                "Verifica los permisos de BASE_DIR en el servidor."
            )
        )
    except Exception as e:
        logger.error("Error al crear carpeta del área '%s': %s", ruta_fisica, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Área creada en BD, pero falló la creación de la carpeta física: {e}"
        )

    # ── Registrar la ruta raíz en la tabla `rutas` ───────────────────────────
    ruta_existente = await db.execute(select(Rutas).where(Rutas.ruta == ruta_logica))
    if not ruta_existente.scalars().first():
        ruta_raiz = Rutas(
            ruta=ruta_logica,
            name=area_data.area_name,
            area_id=new_area.id,
        )
        db.add(ruta_raiz)
        await db.commit()
        logger.info("Ruta raíz registrada en BD: ruta=%r area_id=%d", ruta_logica, new_area.id)

    return new_area


# ==========================================
# GET /areas/ — Listar áreas
# ==========================================
@router.get("/", response_model=list[Area], summary="Obtener Áreas")
async def get_areas(
    incluir_bajas: bool = Query(False, description="Si es true, incluye también las áreas dadas de baja"),
    auth=Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve la lista de áreas.
    - Por defecto solo retorna las áreas **activas** (deleted_at IS NULL).
    - Con `?incluir_bajas=true` retorna todas (activas + dadas de baja).
      Solo útil para el panel de administración.
    """
    if incluir_bajas:
        result = await db.execute(select(Area))
    else:
        result = await db.execute(select(Area).where(Area.deleted_at.is_(None)))
    return result.scalars().all()


# ==========================================
# GET /areas/{area_id} — Obtener área por ID
# ==========================================
@router.get("/{area_id}", response_model=Area, summary="Obtener un Área por ID")
async def get_area(
    area_id: int,
    auth=Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve los datos de un área específica por su ID.
    Funciona tanto para áreas activas como dadas de baja.
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
async def update_area(
    area_id: int,
    area_update: AreaUpdate,
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Actualiza parcialmente los datos de un área existente.
    Solo se pueden editar áreas activas (no dadas de baja).
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )

    if area.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El área '{area.area_name}' está dada de baja. Reactívala antes de editarla."
        )

    # Si se quiere cambiar el nombre, verificar que no exista otro con ese nombre
    if area_update.area_name and area_update.area_name != area.area_name:
        dup_result = await db.execute(
            select(Area).where(Area.area_name == area_update.area_name, Area.deleted_at.is_(None))
        )
        if dup_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un área activa con el nombre '{area_update.area_name}'."
            )

    update_data = area_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(area, key, value)

    db.add(area)
    await db.commit()
    await db.refresh(area)
    return area


# ==========================================
# POST /areas/{area_id}/baja — Dar de baja
# ==========================================
@router.post(
    "/{area_id}/baja",
    response_model=Area,
    summary="Dar de baja un Área (Soft Delete)",
)
async def dar_baja_area(
    area_id: int,
    current_user: User = Depends(get_active_user),
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Da de baja un área marcándola con `deleted_at` y `deleted_by`.

    El área y todos sus datos (rutas, usuarios, carpetas físicas) **se conservan
    intactos**. Solo deja de aparecer en los listados normales y los usuarios
    del área ya no podrán iniciar sesión normalmente.

    Para reactivarla usar el endpoint `/areas/{id}/reactivar`.

    Solo accesible por Superadmin.
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )

    if area.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El área '{area.area_name}' ya está dada de baja."
        )

    area.deleted_at = datetime.now(timezone.utc)
    area.deleted_by = current_user.id

    db.add(area)
    await db.commit()
    await db.refresh(area)

    logger.info(
        "Área dada de baja: id=%d name=%r por user_id=%d",
        area_id, area.area_name, current_user.id
    )
    return area


# ==========================================
# POST /areas/{area_id}/reactivar — Reactivar
# ==========================================
@router.post(
    "/{area_id}/reactivar",
    response_model=Area,
    summary="Reactivar un Área dada de baja",
)
async def reactivar_area(
    area_id: int,
    auth: tuple = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Reactiva un área previamente dada de baja.
    Limpia `deleted_at` y `deleted_by`, dejando el área activa de nuevo.

    Solo accesible por Superadmin.
    """
    result = await db.execute(select(Area).where(Area.id == area_id))
    area = result.scalars().first()
    if not area:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el área con ID {area_id}."
        )

    if area.deleted_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El área '{area.area_name}' ya está activa."
        )

    area.deleted_at = None
    area.deleted_by = None

    db.add(area)
    await db.commit()
    await db.refresh(area)

    logger.info("Área reactivada: id=%d name=%r", area_id, area.area_name)
    return area
