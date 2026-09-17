import os
import shutil
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user, get_current_user_ext
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.models.user_trash_model import UserTrash
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.rol_model import Rol
from sqlalchemy import or_, delete as sql_delete

router = APIRouter()

class TrashRequest(BaseModel):
    area: str
    subpath: str = "/"
    filenames: List[str]

class RestoreRequest(BaseModel):
    trash_ids: List[int]

async def _get_user_area_name(user_ext: Users_extend, db: AsyncSession) -> str:
    result = await db.execute(select(Area).where(Area.id == user_ext.area_id))
    area_obj = result.scalars().first()
    return area_obj.area_name if area_obj else ""

async def _get_user_privilege(user_ext: Users_extend, db: AsyncSession) -> int:
    result = await db.execute(select(Rol).where(Rol.id == user_ext.rol_id))
    rol_obj = result.scalars().first()
    return rol_obj.privilege_level if rol_obj else 0

@router.post("/trash", summary="Mover elementos a la papelera")
async def move_to_trash(
    req: TrashRequest,
    current_user: User = Depends(get_active_user),
    user_ext: Users_extend = Depends(get_current_user_ext),
    db: AsyncSession = Depends(get_db_session)
):
    # Verificar que el área solicitada sea la misma área del usuario
    user_area_name = await _get_user_area_name(user_ext, db)
    if not user_area_name or user_area_name.lower() != req.area.lower():
        raise HTTPException(
            status_code=403, 
            detail="Solo puedes eliminar archivos que pertenecen a tu propia área."
        )

    # Verificar permisos (requiere delete)
    await check_folder_access(
        area=req.area,
        subpath=req.subpath,
        required_access="delete",
        current_user=current_user,
        db=db,
    )

    safe_subpath = req.subpath.strip("/")
    
    trash_dir = os.path.join(BASE_DIR, ".trash", str(current_user.id))
    os.makedirs(trash_dir, exist_ok=True)

    details = []
    trashed_count = 0
    failed_count = 0

    for filename in req.filenames:
        if ".." in filename or "/" in filename:
            details.append({"filename": filename, "status": "error", "reason": "Nombre inválido"})
            failed_count += 1
            continue
            
        ruta_real = (
            os.path.join(BASE_DIR, req.area.upper(), safe_subpath, filename)
            if safe_subpath
            else os.path.join(BASE_DIR, req.area.upper(), filename)
        )

        if not os.path.exists(ruta_real):
            details.append({"filename": filename, "status": "error", "reason": "No existe"})
            failed_count += 1
            continue
            
        es_carpeta = os.path.isdir(ruta_real)
        size_bytes = os.path.getsize(ruta_real) if not es_carpeta else None
        
        timestamp = datetime.now().strftime("%Y%md%H%M%S")
        trash_filename = f"{timestamp}_{filename}"
        trash_path = os.path.join(trash_dir, trash_filename)
        
        try:
            shutil.move(ruta_real, trash_path)
            
            # Limpiar de la tabla Rutas si era carpeta
            logical_prefix = (
                f"{req.area.upper()}/{safe_subpath}/{filename}".replace("//", "/")
                if safe_subpath
                else f"{req.area.upper()}/{filename}"
            )
            await db.execute(
                sql_delete(Rutas).where(
                    or_(
                        Rutas.ruta == logical_prefix,
                        Rutas.ruta.like(f"{logical_prefix}/%")
                    )
                )
            )
            
            # Registrar en user_trash
            trash_entry = UserTrash(
                user_id=current_user.id,
                area=req.area,
                original_subpath=req.subpath,
                filename=filename,
                trash_path=trash_path,
                item_type="folder" if es_carpeta else "file",
                size_bytes=size_bytes,
                deleted_by=current_user.id
            )
            db.add(trash_entry)
            await db.flush() # Para obtener el ID
            
            details.append({"filename": filename, "status": "ok", "trash_id": trash_entry.id})
            trashed_count += 1
            
        except Exception as e:
            details.append({"filename": filename, "status": "error", "reason": str(e)})
            failed_count += 1

    await db.commit()
    return {
        "trashed": trashed_count,
        "failed": failed_count,
        "details": details
    }

@router.post("/restore", summary="Restaurar elementos de la papelera")
async def restore_from_trash(
    req: RestoreRequest,
    current_user: User = Depends(get_active_user),
    user_ext: Users_extend = Depends(get_current_user_ext),
    db: AsyncSession = Depends(get_db_session)
):
    user_area_name = await _get_user_area_name(user_ext, db)
    privilege_level = await _get_user_privilege(user_ext, db)
    
    restored_count = 0
    failed_count = 0
    
    for t_id in req.trash_ids:
        result = await db.execute(select(UserTrash).where(UserTrash.id == t_id))
        trash_item = result.scalars().first()
        
        if not trash_item or trash_item.deleted_at or trash_item.restored_at:
            failed_count += 1
            continue
            
        # Verificar permisos según nivel de privilegio
        if privilege_level == 2:
            pass  # Superadmin: puede restaurar todo
        elif privilege_level == 1:
            # Admin de Área: solo su área
            if not user_area_name or trash_item.area.lower() != user_area_name.lower():
                failed_count += 1
                continue
        else:
            # Usuario regular: solo lo que él mismo borró
            if trash_item.deleted_by != current_user.id:
                failed_count += 1
                continue
            
        safe_subpath = trash_item.original_subpath.strip("/")
        dest_dir = (
            os.path.join(BASE_DIR, trash_item.area.upper(), safe_subpath)
            if safe_subpath
            else os.path.join(BASE_DIR, trash_item.area.upper())
        )
        
        os.makedirs(dest_dir, exist_ok=True)
        
        dest_filename = trash_item.filename
        dest_path = os.path.join(dest_dir, dest_filename)
        
        # Manejo de colisiones
        if os.path.exists(dest_path):
            timestamp = datetime.now().strftime("%Y%md%H%M%S")
            if trash_item.item_type == "file" and "." in dest_filename:
                name_part, ext_part = dest_filename.rsplit(".", 1)
                dest_filename = f"{name_part}_restaurado_{timestamp}.{ext_part}"
            else:
                dest_filename = f"{dest_filename}_restaurado_{timestamp}"
            dest_path = os.path.join(dest_dir, dest_filename)
            
        try:
            shutil.move(trash_item.trash_path, dest_path)
            trash_item.restored_at = datetime.now()
            trash_item.restored_by = current_user.id
            db.add(trash_item)
            restored_count += 1
        except Exception:
            failed_count += 1
            
    await db.commit()
    return {
        "restored": restored_count,
        "failed": failed_count
    }

@router.get("/trash", summary="Listar elementos en papelera")
async def list_trash(
    current_user: User = Depends(get_active_user),
    user_ext: Users_extend = Depends(get_current_user_ext),
    db: AsyncSession = Depends(get_db_session)
):
    user_area_name = await _get_user_area_name(user_ext, db)
    privilege_level = await _get_user_privilege(user_ext, db)
    
    query = select(UserTrash).where(
        UserTrash.deleted_at == None,
        UserTrash.restored_at == None
    )
    
    if privilege_level == 2:
        pass  # Superadmin ve todo
    elif privilege_level == 1:
        # Admin de área ve toda su área
        if not user_area_name:
            return []
        query = query.where(UserTrash.area.ilike(user_area_name))
    else:
        # Usuario regular solo ve lo suyo
        query = query.where(UserTrash.deleted_by == current_user.id)
        
    result = await db.execute(query)
    
    items = result.scalars().all()
    return [
        {
            "trash_id": item.id,
            "filename": item.filename,
            "area": item.area,
            "original_subpath": item.original_subpath,
            "item_type": item.item_type,
            "size_bytes": item.size_bytes,
            "trashed_at": item.trashed_at,
            "deleted_by": item.deleted_by,
        }
        for item in items
    ]
