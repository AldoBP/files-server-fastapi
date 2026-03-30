import os
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


@router.post("/upload", summary="Subir un archivo a una carpeta del servidor")
async def upload_file(
    area: str = Form(...),
    subpath: str = Form(default="/"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Sube un archivo a la carpeta indicada dentro del share Samba.

    - **area**: Área destino (ej: 'CONTABILIDAD')
    - **subpath**: Subcarpeta relativa (ej: '/' raíz, '/2024/Enero' subcarpeta)
    - **file**: El archivo a subir (multipart/form-data)
    """
    await check_folder_access(area=area, subpath=subpath, required_access="allow_write", current_user=current_user, db=db)

    if ".." in subpath or ".." in (file.filename or ""):
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    safe_filename = os.path.basename(file.filename or "archivo_sin_nombre")
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

    safe_subpath = subpath.strip("/")
    ruta_destino = os.path.join(BASE_DIR, area.upper(), safe_subpath) if safe_subpath else os.path.join(BASE_DIR, area.upper())

    if not os.path.isdir(ruta_destino):
        raise HTTPException(status_code=404, detail=f"La carpeta de destino no existe: /{area.upper()}/{safe_subpath}")

    ruta_archivo = os.path.join(ruta_destino, safe_filename)
    if os.path.exists(ruta_archivo):
        raise HTTPException(status_code=409, detail=f"Ya existe un archivo con ese nombre: {safe_filename}")

    try:
        CHUNK_SIZE = 1024 * 1024  # 1 MB por chunk
        with open(ruta_archivo, "wb") as f:
            while chunk := await file.read(CHUNK_SIZE):
                f.write(chunk)

        size_bytes = os.path.getsize(ruta_archivo)
        size_kb = size_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        ruta_logica = f"/{area.upper()}/{safe_subpath}/{safe_filename}".replace("//", "/")

        return {"message": "Archivo subido exitosamente", "filename": safe_filename, "size": size_str, "path": ruta_logica}

    except PermissionError:
        raise HTTPException(status_code=403, detail="El servidor rechazó el permiso de escritura en el share Samba")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Error del sistema al guardar el archivo: {e}")
    finally:
        await file.close()
