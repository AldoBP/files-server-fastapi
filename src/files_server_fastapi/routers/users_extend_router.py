from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
from pydantic import BaseModel

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol


from pydantic import BaseModel, Field, model_validator

class UserExtendCreate(BaseModel):
    user_id: int
    area_id: int
    rol_id: int = Field(alias="role_id", default=None)
    puesto: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def allow_both_names(cls, data: dict):
        if 'role_id' in data and 'rol_id' not in data:
            data['rol_id'] = data['role_id']
        elif 'rol_id' in data and 'role_id' not in data:
            data['role_id'] = data['rol_id']
        return data

class UserExtendResponse(BaseModel):
    id: int
    user_id: int
    area_id: int
    rol_id: int
    role_id: int  # Añadimos alias virtual para el frontend
    puesto: Optional[str] = None
    
    class Config:
        from_attributes = True

class UserExtendUpdate(BaseModel):
    area_id: Optional[int] = None
    rol_id: Optional[int] = None
    puesto: Optional[str] = None

    @model_validator(mode='before')
    @classmethod
    def allow_both_names(cls, data: dict):
        if 'role_id' in data and 'rol_id' not in data:
            data['rol_id'] = data['role_id']
        return data


router = APIRouter(prefix="/users-extend", tags=["Extensión de Usuarios"])


async def _validate_area_and_rol(area_id: Optional[int], rol_id: Optional[int], db: AsyncSession):
    """Valida que el area_id y rol_id existan en la base de datos."""
    if area_id is not None:
        area_result = await db.execute(select(Area).where(Area.id == area_id))
        if not area_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No existe un área con ID {area_id}. Crea el área primero en /areas/."
            )
    if rol_id is not None:
        rol_result = await db.execute(select(Rol).where(Rol.id == rol_id))
        if not rol_result.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No existe un rol con ID {rol_id}."
            )


# ==========================================
# POST /users-extend/ — Vincular usuario
# ==========================================
@router.post("/", response_model=Users_extend, status_code=status.HTTP_201_CREATED, summary="Vincular Usuario con Área y Rol")
async def create_user_extend(user_ext: UserExtendCreate, db: AsyncSession = Depends(get_db_session)):
    """
    Vincula un usuario con un área y rol. Valida que el área y rol existan antes de insertar.
    """
    # Verificar que no exista ya una extensión para este usuario
    existing_result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_ext.user_id))
    if existing_result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El usuario con ID {user_ext.user_id} ya tiene datos de extensión. Usa PATCH para actualizar."
        )

    # Validar que area_id y rol_id existen
    await _validate_area_and_rol(user_ext.area_id, user_ext.rol_id, db)

    new_user_ext = Users_extend(**user_ext.model_dump())
    db.add(new_user_ext)
    await db.commit()
    await db.refresh(new_user_ext)
    return new_user_ext


# ==========================================
# GET /users-extend/ — Listar todos
# ==========================================
@router.get("/", response_model=list[UserExtendResponse], summary="Ver vínculos de usuarios")
async def get_users_extend(db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend))
    users = result.scalars().all()
    # Construimos la respuesta manual inyectando role_id
    response = []
    for u in users:
        u_dict = u.model_dump()
        u_dict["role_id"] = u.rol_id
        response.append(u_dict)
    return response


# ==========================================
# GET /users-extend/by-area/{area_id}
# ==========================================
@router.get("/by-area/{area_id}", response_model=list[UserExtendResponse], summary="Obtener usuarios de un área")
async def get_users_by_area(area_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend).where(Users_extend.area_id == area_id))
    users = result.scalars().all()
    response = []
    for u in users:
        u_dict = u.model_dump()
        u_dict["role_id"] = u.rol_id
        response.append(u_dict)
    return response


# ==========================================
# GET /users-extend/by-user/{user_id}
# ==========================================
@router.get("/by-user/{user_id}", summary="Obtener Área y Rol de un Usuario específico")
async def get_user_permissions(user_id: int, db: AsyncSession = Depends(get_db_session)):
    result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_id))
    user_ext = result.scalars().first()

    if not user_ext:
        return {"role_id": None, "area_id": None, "puesto": None}

    return {"role_id": user_ext.rol_id, "area_id": user_ext.area_id, "puesto": user_ext.puesto}


# ==========================================
# PATCH /users-extend/{user_id} — Actualizar
# ==========================================
@router.patch("/{user_id}", response_model=UserExtendResponse, summary="Actualizar datos de extensión de usuario")
async def update_user_extend(user_id: int, user_ext_update: UserExtendUpdate, db: AsyncSession = Depends(get_db_session)):
    from sqlmodel import or_
    
    # Buscamos por user_id (lo ideal) o por el ID interno del registro (si el frontend se confunde)
    result = await db.execute(
        select(Users_extend).where(
            or_(Users_extend.user_id == user_id, Users_extend.id == user_id)
        )
    )
    user_ext = result.scalars().first()

    if not user_ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado en la extensión."
        )

    # Validar area_id y rol_id si se están actualizando
    await _validate_area_and_rol(user_ext_update.area_id, user_ext_update.rol_id, db)

    # IMPRIMIMOS EL PAYLOAD PARA VER QUÉ LLEGA REALMENTE
    print(f"\n[DEBUG] PAYLOAD RECIBIDO DEL FRONTEND PARA USER {user_id}: {user_ext_update.model_dump()}")
    print(f"[DEBUG] EXCLUDE UNSET: {user_ext_update.model_dump(exclude_unset=True)}\n")

    # Extraer los datos enviados por el frontend
    update_data = user_ext_update.model_dump(exclude_unset=True)
    
    # ¡TRUCO! Si nuestro model_validator metió el rol_id, Pydantic lo excluye en exclude_unset
    # porque no venía originalmente con ese nombre exacto. Lo forzamos a entrar a mano:
    if user_ext_update.rol_id is not None:
        update_data["rol_id"] = user_ext_update.rol_id

    for key, value in update_data.items():
        setattr(user_ext, key, value)

    db.add(user_ext)
    await db.commit()
    await db.refresh(user_ext)

    u_dict = user_ext.model_dump()
    u_dict["role_id"] = user_ext.rol_id
    return u_dict


# ==========================================
# DELETE /users-extend/{user_id} — Eliminar
# ==========================================
@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar extensión de usuario")
async def delete_user_extend(user_id: int, db: AsyncSession = Depends(get_db_session)):
    """
    Elimina el vínculo de área y rol de un usuario.
    """
    result = await db.execute(select(Users_extend).where(Users_extend.user_id == user_id))
    user_ext = result.scalars().first()

    if not user_ext:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario con ID {user_id} no encontrado en la extensión."
        )

    await db.delete(user_ext)
    await db.commit()
