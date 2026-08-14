import os
import shutil
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from typing import List, Optional

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.files.path_utils import normalize_subpath, build_logical_path

router = APIRouter()

class MoveRequest(BaseModel):
    src_area: str
    src_subpath: str
    filenames: list[str]
    dst_area: str
    dst_subpath: str

class CopyRequest(BaseModel):
    src_area: str
    src_subpath: str
    filenames: list[str]
    dst_area: str
    dst_subpath: str

@router.post("/move", summary="Mover uno o varios archivos/carpetas")
async def move_items(
    req: MoveRequest,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    if not req.filenames:
        raise HTTPException(status_code=400, detail="La lista de archivos está vacía")

    for f in req.filenames:
        if ".." in f or "/" in f:
            raise HTTPException(status_code=400, detail=f"Nombre de archivo inválido: {f}")

    if ".." in req.src_subpath or ".." in req.dst_subpath:
        raise HTTPException(status_code=400, detail="Subpath inválido")

    await check_folder_access(
        area=req.src_area, subpath=req.src_subpath, required_access="delete",
        current_user=current_user, db=db
    )
    
    await check_folder_access(
        area=req.dst_area, subpath=req.dst_subpath, required_access="upload",
        current_user=current_user, db=db
    )

    src_subpath_clean = normalize_subpath(req.src_area, req.src_subpath)
    dst_subpath_clean = normalize_subpath(req.dst_area, req.dst_subpath)
    
    src_dir = os.path.join(BASE_DIR, req.src_area.upper(), src_subpath_clean) if src_subpath_clean else os.path.join(BASE_DIR, req.src_area.upper())
    dst_dir = os.path.join(BASE_DIR, req.dst_area.upper(), dst_subpath_clean) if dst_subpath_clean else os.path.join(BASE_DIR, req.dst_area.upper())
    
    if src_dir == dst_dir:
         return {"results": [], "moved": 0, "failed": 0, "message": "Origen y destino son los mismos"}

    # Obtener el area_id del destino por si se mueven carpetas
    dst_area_query = await db.execute(select(Area).where(Area.area_name.ilike(req.dst_area)))
    dst_area_obj = dst_area_query.scalars().first()

    results = []
    moved = 0
    failed = 0

    for filename in req.filenames:
        src_path = os.path.join(src_dir, filename)
        dst_path = os.path.join(dst_dir, filename)
        
        if not os.path.exists(src_path):
            results.append({"filename": filename, "status": "error", "detail": "No existe en origen"})
            failed += 1
            continue

        if os.path.exists(dst_path):
            results.append({"filename": filename, "status": "error", "detail": "Ya existe en destino"})
            failed += 1
            continue

        is_dir = os.path.isdir(src_path)
        
        try:
            shutil.move(src_path, dst_path)
            moved += 1
            results.append({"filename": filename, "status": "ok"})
            
            # DB logic for folders
            if is_dir and dst_area_obj:
                old_logical_path = build_logical_path(req.src_area, req.src_subpath, filename)
                new_logical_path = build_logical_path(req.dst_area, req.dst_subpath, filename)

                # Update the main folder and all subfolders
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
                    # Reemplazar el prefijo
                    new_ruta_str = new_logical_path + ruta.ruta[len(old_logical_path):]
                    ruta.ruta = new_ruta_str
                    ruta.area_id = dst_area_obj.id
                await db.commit()

        except PermissionError:
            results.append({"filename": filename, "status": "error", "detail": "Permiso denegado por el OS"})
            failed += 1
        except Exception as e:
            results.append({"filename": filename, "status": "error", "detail": str(e)})
            failed += 1
            
    return {"results": results, "moved": moved, "failed": failed}

@router.post("/copy", summary="Copiar uno o varios archivos/carpetas")
async def copy_items(
    req: CopyRequest,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    if not req.filenames:
        raise HTTPException(status_code=400, detail="La lista de archivos está vacía")

    for f in req.filenames:
        if ".." in f or "/" in f:
            raise HTTPException(status_code=400, detail=f"Nombre de archivo inválido: {f}")

    if ".." in req.src_subpath or ".." in req.dst_subpath:
        raise HTTPException(status_code=400, detail="Subpath inválido")

    await check_folder_access(
        area=req.src_area, subpath=req.src_subpath, required_access="view",
        current_user=current_user, db=db
    )
    
    await check_folder_access(
        area=req.dst_area, subpath=req.dst_subpath, required_access="upload",
        current_user=current_user, db=db
    )

    src_subpath_clean = normalize_subpath(req.src_area, req.src_subpath)
    dst_subpath_clean = normalize_subpath(req.dst_area, req.dst_subpath)
    
    src_dir = os.path.join(BASE_DIR, req.src_area.upper(), src_subpath_clean) if src_subpath_clean else os.path.join(BASE_DIR, req.src_area.upper())
    dst_dir = os.path.join(BASE_DIR, req.dst_area.upper(), dst_subpath_clean) if dst_subpath_clean else os.path.join(BASE_DIR, req.dst_area.upper())
    
    if src_dir == dst_dir:
         return {"results": [], "copied": 0, "failed": 0, "message": "Origen y destino son los mismos"}

    # Obtener el area_id del destino por si se copian carpetas
    dst_area_query = await db.execute(select(Area).where(Area.area_name.ilike(req.dst_area)))
    dst_area_obj = dst_area_query.scalars().first()

    results = []
    copied = 0
    failed = 0
    
    # Para copy_tree, necesitamos duplicar en la DB
    async def duplicate_rutas_db(old_prefix: str, new_prefix: str, dst_area_id: int):
        res_rutas = await db.execute(
            select(Rutas).where(
                or_(
                    Rutas.ruta == old_prefix,
                    Rutas.ruta.like(f"{old_prefix}/%")
                )
            )
        )
        rutas_to_copy = res_rutas.scalars().all()
        for ruta in rutas_to_copy:
            new_ruta_str = new_prefix + ruta.ruta[len(old_prefix):]
            nueva_ruta = Rutas(
                ruta=new_ruta_str,
                name=ruta.name,
                area_id=dst_area_id
            )
            db.add(nueva_ruta)
        await db.commit()

    for filename in req.filenames:
        src_path = os.path.join(src_dir, filename)
        dst_path = os.path.join(dst_dir, filename)
        
        if not os.path.exists(src_path):
            results.append({"filename": filename, "status": "error", "detail": "No existe en origen"})
            failed += 1
            continue

        if os.path.exists(dst_path):
            results.append({"filename": filename, "status": "error", "detail": "Ya existe en destino"})
            failed += 1
            continue
            
        is_dir = os.path.isdir(src_path)
        
        try:
            if is_dir:
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy2(src_path, dst_path)
                
            copied += 1
            results.append({"filename": filename, "status": "ok"})
            
            if is_dir and dst_area_obj:
                old_logical_path = build_logical_path(req.src_area, req.src_subpath, filename)
                new_logical_path = build_logical_path(req.dst_area, req.dst_subpath, filename)
                
                await duplicate_rutas_db(old_logical_path, new_logical_path, dst_area_obj.id)
                
        except PermissionError:
            results.append({"filename": filename, "status": "error", "detail": "Permiso denegado por el OS"})
            failed += 1
        except Exception as e:
            results.append({"filename": filename, "status": "error", "detail": str(e)})
            failed += 1

    return {"results": results, "copied": copied, "failed": failed}
