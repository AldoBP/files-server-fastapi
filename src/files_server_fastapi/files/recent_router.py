import os
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.models.user_file_access_model import UserFileAccess
from files_server_fastapi.files.dependencies import _resolve_user_context, resolve_effective_access, can_view
from files_server_fastapi.files.constants import BASE_DIR

router = APIRouter()

@router.get("/recent", summary="Archivos recientes")
async def get_recent_files(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    # Obtener historial de acceso
    result = await db.execute(
        select(UserFileAccess)
        .where(UserFileAccess.user_id == current_user.id)
        .order_by(UserFileAccess.accessed_at.desc())
        .limit(limit * 2) # Buscamos más por si algunos están eliminados
    )
    
    access_logs = result.scalars().all()
    
    recent_files = []
    
    for log in access_logs:
        if len(recent_files) >= limit:
            break
            
        safe_subpath = log.subpath.strip("/")
        ruta_real = (
            os.path.join(BASE_DIR, log.area.upper(), safe_subpath, log.filename)
            if safe_subpath
            else os.path.join(BASE_DIR, log.area.upper(), log.filename)
        )
        
        # 1. Si no existe (está en la papelera o borrado físicamente), saltarlo
        if not os.path.exists(ruta_real):
            continue
            
        # 2. Verificar permisos actuales (ACLs pueden cambiar)
        is_super_admin, user_ext_in_area = await _resolve_user_context(current_user, log.area, db)
        
        effective = await resolve_effective_access(
            area=log.area,
            subpath=log.subpath,
            user_id=current_user.id,
            user_ext_in_area=user_ext_in_area,
            is_super_admin=is_super_admin,
            db=db,
        )
        
        if effective and can_view(effective):
            is_dir = os.path.isdir(ruta_real)
            recent_files.append({
                "filename": log.filename,
                "area": log.area,
                "subpath": log.subpath,
                "item_type": "folder" if is_dir else "file",
                "size_bytes": os.path.getsize(ruta_real) if not is_dir else None,
                "accessed_at": log.accessed_at
            })
            
    return recent_files
