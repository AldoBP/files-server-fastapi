import os
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access
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
        logical_path_full = f"/{req.area.upper()}/{subpath}".replace("//", "/")
        
        parts = logical_path_full.strip("/").split("/")
        folder_name = parts[-1] if len(parts) > 0 else req.area.upper()

        # Mapear permisos del Frontend ("EDITOR" / "VIEWER") a tipos de DB ("allow_write" / "allow_read")
        db_access_type = "allow_read" # Por defecto
        if acl_item.permission.upper() == "EDITOR":
            db_access_type = "allow_write"
        elif acl_item.permission.upper() == "DENY":
            db_access_type = "deny_all"

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
