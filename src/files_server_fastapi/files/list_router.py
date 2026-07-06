import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, or_

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user

from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import (
    check_folder_access,
    resolve_effective_access,
    _resolve_user_context,
)
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.rutas_model import Rutas

router = APIRouter()


@router.get("/list", summary="Listar archivos de una carpeta")
async def list_directory(
    area: str,
    subpath: str = "/",
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve el contenido de una carpeta dentro del área indicada.
    Las subcarpetas a las que el usuario no tiene acceso (deny_all o sin regla)
    son omitidas silenciosamente del resultado — no aparecen en el JSON.
    Los archivos en un directorio accesible siempre se devuelven.
    """
    if ".." in subpath:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    # ── 1. Verificar acceso al directorio padre solicitado ───────────────────
    # Reutiliza check_folder_access pero necesitamos también el contexto del usuario
    # para las verificaciones de subcarpetas, así que lo resolvemos aquí.
    is_super_admin, user_ext_in_area = await _resolve_user_context(current_user, area, db)

    # Importar check_folder_access como función directa para reusar su lógica
    from files_server_fastapi.files.dependencies import resolve_effective_access

    parent_access = await resolve_effective_access(
        area=area,
        subpath=subpath,
        user_id=current_user.id,
        user_ext_in_area=user_ext_in_area,
        is_super_admin=is_super_admin,
        db=db,
    )

    if parent_access is None or parent_access == "deny_all":
        raise HTTPException(status_code=403, detail="Acceso denegado a este directorio.")

    # ── 2. Escanear el directorio físico ─────────────────────────────────────
    safe_subpath = subpath.strip("/")
    ruta_real = (
        os.path.join(BASE_DIR, area.upper(), safe_subpath)
        if safe_subpath
        else os.path.join(BASE_DIR, area.upper())
    )

    if not os.path.exists(ruta_real):
        return []
    if not os.path.isdir(ruta_real):
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    # ── 3. Cargar ACLs del usuario en bulk (una sola query) ──────────────────
    # Trae todos los ACLs del usuario para rutas que empiecen con el área,
    # para evitar N consultas individuales al evaluar cada subcarpeta.
    area_prefix = area.upper()
    res_bulk = await db.execute(
        select(Rutas.ruta, User_Ruta_Access)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(User_Ruta_Access.user_id == current_user.id)
        .where(
            or_(
                Rutas.ruta == area_prefix,
                Rutas.ruta.like(area_prefix + "/%"),
            )
        )
    )
    preloaded_acls: dict[str, User_Ruta_Access] = {
        row[0]: row[1] for row in res_bulk.all()
    }

    # ── 4. Construir el listado filtrando carpetas denegadas ─────────────────
    items = []
    try:
        with os.scandir(ruta_real) as ficheros:
            for fichero in ficheros:
                info = fichero.stat()
                fecha_mod = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")

                if fichero.is_dir():
                    # Evaluar permiso efectivo del usuario para esta subcarpeta
                    child_subpath = (
                        os.path.join(safe_subpath, fichero.name)
                        if safe_subpath
                        else fichero.name
                    ).replace("\\", "/")

                    child_access = await resolve_effective_access(
                        area=area,
                        subpath=child_subpath,
                        user_id=current_user.id,
                        user_ext_in_area=user_ext_in_area,
                        is_super_admin=is_super_admin,
                        db=db,
                        preloaded_acls=preloaded_acls,
                    )

                    # Si no tiene acceso (deny_all o None) → omitir silenciosamente
                    if child_access is None or child_access == "deny_all":
                        continue

                    items.append({
                        "name": fichero.name,
                        "type": "folder",
                        "updated": fecha_mod,
                        "size": "",
                        "locked": False,
                    })

                else:
                    # Archivos: visibles si el padre era accesible (ya verificado arriba)
                    size_kb = info.st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                    items.append({
                        "name": fichero.name,
                        "type": "file",
                        "updated": fecha_mod,
                        "size": size_str,
                        "locked": False,
                    })

        items.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
        return items

    except PermissionError:
        raise HTTPException(status_code=403, detail="Acceso denegado por el sistema operativo")
