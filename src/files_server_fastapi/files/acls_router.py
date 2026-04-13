import os
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access, Permisos
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.users_extend_model import Users_extend

router = APIRouter()

class AclDetail(BaseModel):
    path: str
    permission: str

class AclCreate(BaseModel):
    area: str
    user_id: int
    acls: list[AclDetail]

@router.post("/acls", summary="Asignar acceso a una carpeta específica (ACL)")
async def create_acl(
    req: AclCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Crea o actualiza los accesos (ACLs) enviados desde el frontend.
    """
    # 0. Traducir el ID que manda el frontend (users_extend.id) al verdadero user_id de la tabla Users
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == req.user_id))
    user_ext_obj = ext_result.scalars().first()
    
    if not user_ext_obj:
        raise HTTPException(status_code=404, detail=f"No se encontró ninguna extensión de usuario activa con el ID {req.user_id}.")

    real_user_id = user_ext_obj.user_id

    # 1. Verificar si el Área existe para crear la Ruta adecuadamente
    area_result = await db.execute(select(Area).where(Area.area_name.ilike(req.area)))
    area_obj = area_result.scalars().first()
    if not area_obj:
        raise HTTPException(status_code=404, detail=f"Área '{req.area}' no encontrada")

    processed_acls = []

    for acl_item in req.acls:
        # Limpiar subpath y contruir ruta lógica completa
        subpath = acl_item.path.strip("/")
        area_prefix = req.area.upper()

        # Si la ruta ya empieza con el área (ej: VENTAS/test1), no la volvemos a concatenar
        if subpath.startswith(area_prefix):
            logical_path_full = f"/{subpath}".replace("//", "/")
        else:
            logical_path_full = f"/{area_prefix}/{subpath}".replace("//", "/")

        # Siempre limpiar barras extras al final
        logical_path_full = logical_path_full.rstrip("/")
        if logical_path_full == f"/{area_prefix}":
            logical_path_full = f"/{area_prefix}/"
        
        parts = logical_path_full.strip("/").split("/")
        folder_name = parts[-1] if len(parts) > 0 else req.area.upper()

        # Consultar la DB dinámicamente para averiguar qué acción implica el permiso solicitado de frontend
        perm_result = await db.execute(select(Permisos).where(Permisos.permiso_name.ilike(acl_item.permission)))
        permiso_obj = perm_result.scalars().first()
        
        if permiso_obj:
            db_access_type = permiso_obj.fastapi_action
        else:
            db_access_type = "allow_read" # Fallback extremo si enviaron algo inválido

        # 2. Buscar si la ruta ya existe en la tabla Rutas
        ruta_result = await db.execute(select(Rutas).where(Rutas.ruta == logical_path_full))
        ruta_obj = ruta_result.scalars().first()

        # Si no existe, crearla
        if not ruta_obj:
            ruta_obj = Rutas(
                ruta=logical_path_full,
                name=folder_name,
                area_id=area_obj.id
            )
            db.add(ruta_obj)
            await db.commit()
            await db.refresh(ruta_obj)

        # 3. Asignar el ACL en User_Ruta_Access
        acl_result = await db.execute(
            select(User_Ruta_Access)
            .where(User_Ruta_Access.user_id == real_user_id)
            .where(User_Ruta_Access.ruta_id == ruta_obj.id)
        )
        existing_acl = acl_result.scalars().first()

        if existing_acl:
            existing_acl.access_type = db_access_type
            processed_acls.append(existing_acl.id)
        else:
            new_acl = User_Ruta_Access(
                user_id=real_user_id,
                ruta_id=ruta_obj.id,
                access_type=db_access_type
            )
            db.add(new_acl)
            await db.commit()
            await db.refresh(new_acl)
            processed_acls.append(new_acl.id)

    return {"message": "ACLs asignados correctamente", "processed_acls": processed_acls}

@router.get("/acls", summary="Obtener las carpetas compartidas del usuario")
async def get_user_acls(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Devuelve la lista de rutas (carpetas) a las que el usuario tiene acceso
    mediante asignación directa en la tabla User_Ruta_Access.
    """
    # Buscar el ID real de la tabla Users_extend del usuario activo
    ext_result = await db.execute(select(Users_extend).where(Users_extend.user_id == current_user.id))
    user_exts = ext_result.scalars().all()
    
    if not user_exts:
        return []

    # Se obtienen todos los ACLs del usuario para cualquier ruta (donde no sea deny_all)
    # y hacemos join con Rutas para traer el path
    result = await db.execute(
        select(Rutas.ruta, Rutas.name, User_Ruta_Access.access_type, Area.area_name)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .join(Area, Area.id == Rutas.area_id)
        .where(User_Ruta_Access.user_id == current_user.id)
        .where(User_Ruta_Access.access_type != "deny_all")
    )
    
    # Obtener el mapeo de acciones a nombres (Reverse lookup)
    perm_result = await db.execute(select(Permisos.fastapi_action, Permisos.permiso_name))
    action_to_name = {action: name for action, name in perm_result.all()}

    shared_folders = []
    for row in result.all():
        ruta, nombre, access_type, area_name = row
        shared_folders.append({
            "path": ruta,
            "name": nombre,
            "permission": action_to_name.get(access_type, access_type),
            "area": area_name,
            "type": "folder",
            "is_shared": True
        })

    return {"shared_folders": shared_folders}

@router.get("/acls/user/{user_id}", summary="Obtener los ACLs de un usuario específico")
async def get_specific_user_acls(
    user_id: int,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Devuelve las reglas actuales de un usuario en un formato simple para el modal de React.
    Ejemplo: {"/ruta/1": "EDITOR", "/ruta/2": "VIEWER"}
    """
    # 0. Traducir el ID que manda el frontend (users_extend.id) al verdadero user_id
    ext_result = await db.execute(select(Users_extend).where(Users_extend.id == user_id))
    user_ext_obj = ext_result.scalars().first()
    
    if not user_ext_obj:
        raise HTTPException(status_code=404, detail=f"No se encontró ninguna extensión de usuario con el ID {user_id}.")

    real_user_id = user_ext_obj.user_id

    # 1. Consultar los ACLs en la base de datos
    result = await db.execute(
        select(Rutas.ruta, User_Ruta_Access.access_type)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(User_Ruta_Access.user_id == real_user_id)
    )
    
    # 2. Obtener el mapeo de acciones a nombres (Reverse lookup dinámico)
    perm_result = await db.execute(select(Permisos.fastapi_action, Permisos.permiso_name))
    action_to_name = {action: name for action, name in perm_result.all()}

    # 3. Convertir al formato simple que espera el frontend
    acls_dict = {}
    for ruta, access_type in result.all():
        acls_dict[ruta] = action_to_name.get(access_type, access_type)
    
    return acls_dict
