import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.files.path_utils import normalize_subpath, build_logical_path

router = APIRouter()


class FileCreate(BaseModel):
    area: str
    subpath: str
    file_name: str
    file_type: str  # Ej: 'docx', 'xlsx', 'txt'


@router.post("/create-file", summary="Crear un nuevo archivo en el servidor")
async def create_file(
    req: FileCreate,
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    await check_folder_access(area=req.area, subpath=req.subpath, required_access="upload", current_user=current_user, db=db)

    # Construir el nombre final del archivo con su extensión
    file_ext = req.file_type.strip(".")
    full_file_name = req.file_name.strip()
    if not full_file_name.lower().endswith(f".{file_ext.lower()}"):
        full_file_name = f"{full_file_name}.{file_ext}"

    if ".." in req.subpath or ".." in full_file_name or "/" in full_file_name:
        raise HTTPException(status_code=400, detail="Nombre de archivo o ruta inválida")

    clean_subpath = normalize_subpath(req.area, req.subpath)

    if clean_subpath:
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), clean_subpath, full_file_name)
    else:
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), full_file_name)

    if os.path.exists(ruta_final):
        raise HTTPException(status_code=400, detail="Ya existe un archivo con ese nombre aquí")

    try:
        with open(ruta_final, "wb") as f:
            pass

        return {"message": "Archivo creado exitosamente", "path": build_logical_path(req.area, clean_subpath, full_file_name)}
    except PermissionError:
        raise HTTPException(status_code=403, detail="El servidor rechazó el permiso de escritura")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
