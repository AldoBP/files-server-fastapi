import os
import shutil
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.files.path_utils import build_logical_path
from files_server_fastapi.models.rutas_model import Rutas

router = APIRouter()

class RenameRequest(BaseModel):
    area: str
    subpath: str = "/"
    old_name: str
    new_name: str

@router.post("/rename", summary="Renombrar un archivo o carpeta")
async def rename_item(
    req: RenameRequest,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    # Validar caracteres prohibidos
    invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    if any(char in req.new_name for char in invalid_chars):
        raise HTTPException(
            status_code=400, 
            detail="El nuevo nombre contiene caracteres inválidos"
        )
        
    if ".." in req.subpath or ".." in req.old_name or ".." in req.new_name:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    # Requiere permiso upload
    await check_folder_access(
        area=req.area,
        subpath=req.subpath,
        required_access="upload",
        current_user=current_user,
        db=db,
    )
    
    safe_subpath = req.subpath.strip("/")
    parent_dir = (
        os.path.join(BASE_DIR, req.area.upper(), safe_subpath)
        if safe_subpath
        else os.path.join(BASE_DIR, req.area.upper())
    )
    
    old_path = os.path.join(parent_dir, req.old_name)
    new_path = os.path.join(parent_dir, req.new_name)
    
    if not os.path.exists(old_path):
        raise HTTPException(status_code=404, detail=f"El archivo '{req.old_name}' no existe")
        
    if os.path.exists(new_path):
        raise HTTPException(status_code=409, detail=f"Ya existe un archivo con el nombre '{req.new_name}' en esta carpeta")
        
    is_dir = os.path.isdir(old_path)
    
    # Validar extensión si es un archivo
    if not is_dir:
        old_ext = os.path.splitext(req.old_name)[1].lower()
        new_ext = os.path.splitext(req.new_name)[1].lower()
        if old_ext != new_ext:
            raise HTTPException(
                status_code=400, 
                detail="No se permite cambiar la extensión del archivo al renombrar"
            )

    try:
        os.rename(old_path, new_path)
        
        # Si es carpeta, actualizar registros en tabla Rutas
        if is_dir:
            old_logical_path = build_logical_path(req.area, req.subpath, req.old_name)
            new_logical_path = build_logical_path(req.area, req.subpath, req.new_name)
            
            res_rutas = await db.execute(
                select(Rutas).where(
                    or_(
                        Rutas.ruta == old_logical_path,
                        Rutas.ruta.like(f"{old_logical_path}/%")
                    )
                )
            )
            rutas = res_rutas.scalars().all()
            for ruta in rutas:
                new_ruta_str = new_logical_path + ruta.ruta[len(old_logical_path):]
                ruta.ruta = new_ruta_str
            await db.commit()
            
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado por el OS")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    return {
        "success": True,
        "old_name": req.old_name,
        "new_name": req.new_name
    }
