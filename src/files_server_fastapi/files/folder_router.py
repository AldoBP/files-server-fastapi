import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.files.path_utils import normalize_subpath, build_logical_path
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.area_model import Area

router = APIRouter()


class FolderCreate(BaseModel):
    area: str
    subpath: str
    folder_name: str


@router.post("/folder", summary="Crear una nueva carpeta en el servidor")
async def create_folder(
    req: FolderCreate,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session)
):
    # ── DEBUG ─────────────────────────────────────────────────────────────────
    print(f"[folder_router] INPUT  → area={req.area!r}  subpath={req.subpath!r}  folder_name={req.folder_name!r}")
    # ─────────────────────────────────────────────────────────────────────────

    await check_folder_access(area=req.area, subpath=req.subpath, required_access="allow_write", current_user=current_user, db=db)

    if ".." in req.subpath or ".." in req.folder_name or "/" in req.folder_name:
        raise HTTPException(status_code=400, detail="Nombre de carpeta o ruta inválida")

    # Normalizar el subpath: quitar el área si el frontend ya la incluyó
    clean_subpath = normalize_subpath(req.area, req.subpath)

    # ── DEBUG ─────────────────────────────────────────────────────────────────
    print(f"[folder_router] CLEAN  → clean_subpath={clean_subpath!r}")
    # ─────────────────────────────────────────────────────────────────────────

    # Ruta física en disco
    if clean_subpath:
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), clean_subpath, req.folder_name)
    else:
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), req.folder_name)

    # Ruta lógica para guardar en DB (siempre limpia)
    logical_path_db = build_logical_path(req.area, clean_subpath, req.folder_name)

    # ── DEBUG ─────────────────────────────────────────────────────────────────
    print(f"[folder_router] RESULT → ruta_fisica={ruta_final!r}  logical_path_db={logical_path_db!r}")
    # ─────────────────────────────────────────────────────────────────────────

    try:
        os.makedirs(ruta_final, exist_ok=False)

        # Buscar el área para ligar la ruta
        area_query = await db.execute(select(Area).where(Area.area_name.ilike(req.area)))
        area_obj = area_query.scalars().first()

        # Guardar formalmente la carpeta en base de datos
        if area_obj:
            nueva_ruta = Rutas(
                ruta=logical_path_db,
                name=req.folder_name,
                area_id=area_obj.id
            )
            db.add(nueva_ruta)
            await db.commit()

        return {"message": "Carpeta creada exitosamente", "path": ruta_final}
    except FileExistsError:
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre aquí")
    except PermissionError:
        raise HTTPException(status_code=403, detail="El servidor rechazó el permiso de escritura")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
