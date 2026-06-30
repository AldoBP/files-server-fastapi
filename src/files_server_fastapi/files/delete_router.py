import os
import shutil
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete as sql_delete, or_

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_verified_user, User
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access
from files_server_fastapi.models.rutas_model import Rutas

router = APIRouter()


class DeleteRequest(BaseModel):
    area: str
    subpath: str = "/"
    filename: str  # nombre del archivo o carpeta a eliminar


@router.delete("/delete", summary="Eliminar un archivo o carpeta del servidor")
async def delete_item(
    req: DeleteRequest,
    current_user: User = Depends(get_current_verified_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Elimina un archivo o carpeta del área indicada.

    - Requiere permiso **web_full** sobre el subpath.
    - Si el objetivo es una carpeta **no vacía**, se elimina recursivamente todo su contenido.
    - Si era una carpeta registrada en la base de datos, también se elimina su registro (y los de subcarpetas).
    - La base de datos se limpia **solo si** la eliminación física tuvo éxito, evitando registros huérfanos.
    """
    # ── 1. Validar rutas ANTES de cualquier lógica de negocio ─────────────────
    # req.filename nunca debe contener separadores de directorio ni secuencias de traversal.
    if ".." in req.subpath or ".." in req.filename or "/" in req.filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre inválido")

    # ── 2. Verificar permiso de eliminación ───────────────────────────────────
    await check_folder_access(
        area=req.area,
        subpath=req.subpath,
        required_access="delete",
        current_user=current_user,
        db=db,
    )

    # ── 3. Construir rutas ────────────────────────────────────────────────────
    safe_name = os.path.basename(req.filename)
    safe_subpath = req.subpath.strip("/")
    ruta_real = (
        os.path.join(BASE_DIR, req.area.upper(), safe_subpath, safe_name)
        if safe_subpath
        else os.path.join(BASE_DIR, req.area.upper(), safe_name)
    )

    if not os.path.exists(ruta_real):
        raise HTTPException(status_code=404, detail=f"No se encontró: {safe_name}")

    es_carpeta = os.path.isdir(ruta_real)

    # Prefijo lógico para limpiar registros en BD (coincide con el formato sin barra inicial)
    logical_prefix = (
        f"{req.area.upper()}/{safe_subpath}/{safe_name}".replace("//", "/")
        if safe_subpath
        else f"{req.area.upper()}/{safe_name}"
    )

    # ── 4. Eliminación física primero — BD solo si el disco tuvo éxito ────────
    try:
        if es_carpeta:
            shutil.rmtree(ruta_real)
        else:
            os.remove(ruta_real)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permiso denegado por el sistema operativo")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # ── 5. Limpiar registros en BD (solo si la eliminación física fue exitosa) ─
    # Se eliminan tanto la carpeta como todas sus subcarpetas registradas en Rutas.
    # Para archivos regulares no suele haber entrada en Rutas, pero el DELETE
    # es seguro (no borra nada si no hay coincidencia).
    await db.execute(
        sql_delete(Rutas).where(
            or_(
                Rutas.ruta == logical_prefix,
                Rutas.ruta.like(f"{logical_prefix}/%")
            )
        )
    )
    await db.commit()

    tipo = "folder" if es_carpeta else "file"
    label = "Carpeta" if es_carpeta else "Archivo"
    return {
        "message": f"{label} '{safe_name}' eliminado exitosamente",
        "type": tipo,
        "path": ruta_real,
    }
