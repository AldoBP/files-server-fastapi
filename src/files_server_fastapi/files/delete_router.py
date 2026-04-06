import os
import shutil
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.models.rutas_model import Rutas

router = APIRouter()


class DeleteRequest(BaseModel):
    area: str
    subpath: str = "/"
    name: str  # nombre del archivo o carpeta a eliminar


@router.delete("/delete", summary="Eliminar un archivo o carpeta del servidor")
async def delete_item(
    req: DeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Elimina un archivo o carpeta del área indicada.

    - Requiere permiso **allow_write** sobre el subpath.
    - Si el objetivo es una carpeta **no vacía**, se elimina recursivamente todo su contenido.
    - Si era una carpeta registrada en la base de datos, también se elimina su registro (y los de subcarpetas).
    """
    # Permiso de escritura sobre el directorio padre
    await check_folder_access(
        area=req.area,
        subpath=req.subpath,
        required_access="allow_write",
        current_user=current_user,
        db=db,
    )

    if ".." in req.subpath or ".." in req.name or ("/" in req.name and req.name != "/"):
        raise HTTPException(status_code=400, detail="Ruta o nombre inválido")

    safe_name = os.path.basename(req.name)
    safe_subpath = req.subpath.strip("/")
    ruta_real = (
        os.path.join(BASE_DIR, req.area.upper(), safe_subpath, safe_name)
        if safe_subpath
        else os.path.join(BASE_DIR, req.area.upper(), safe_name)
    )

    if not os.path.exists(ruta_real):
        raise HTTPException(status_code=404, detail=f"No se encontró: {safe_name}")

    es_carpeta = os.path.isdir(ruta_real)

    try:
        if es_carpeta:
            shutil.rmtree(ruta_real)

            # Eliminar también todos los registros de Rutas que comiencen con ese path lógico
            logical_prefix = (
                f"/{req.area.upper()}/{safe_subpath}/{safe_name}".replace("//", "/")
                if safe_subpath
                else f"/{req.area.upper()}/{safe_name}"
            )
            await db.execute(
                sql_delete(Rutas).where(Rutas.ruta.like(f"{logical_prefix}%"))
            )
            await db.commit()

            return {"message": f"Carpeta '{safe_name}' eliminada exitosamente", "type": "folder", "path": ruta_real}
        else:
            os.remove(ruta_real)
            return {"message": f"Archivo '{safe_name}' eliminado exitosamente", "type": "file", "path": ruta_real}

    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado por el sistema operativo")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
