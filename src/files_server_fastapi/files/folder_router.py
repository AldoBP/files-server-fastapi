import os
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


class FolderCreate(BaseModel):
    area: str
    subpath: str
    folder_name: str


@router.post("/folder", summary="Crear una nueva carpeta en el servidor")
async def create_folder(
    req: FolderCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    await check_folder_access(area=req.area, subpath=req.subpath, required_access="allow_write", current_user=current_user, db=db)

    if ".." in req.subpath or ".." in req.folder_name or "/" in req.folder_name:
        raise HTTPException(status_code=400, detail="Nombre de carpeta o ruta inválida")

    safe_subpath = req.subpath.strip("/")
    ruta_final = os.path.join(BASE_DIR, req.area.upper(), safe_subpath, req.folder_name) if safe_subpath else os.path.join(BASE_DIR, req.area.upper(), req.folder_name)

    try:
        os.makedirs(ruta_final, exist_ok=False)
        return {"message": "Carpeta creada exitosamente", "path": ruta_final}
    except FileExistsError:
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre aquí")
    except PermissionError:
        raise HTTPException(status_code=403, detail="El servidor rechazó el permiso de escritura")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
