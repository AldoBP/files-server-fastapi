import os
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


@router.post("/upload", summary="Subir múltiples archivos a una carpeta del servidor")
async def upload_files(
    area: str = Form(...),
    subpath: str = Form(default="/"),
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Sube uno o múltiples archivos a la carpeta indicada dentro del share Samba.

    - **area**: Área destino (ej: 'CONTABILIDAD')
    - **subpath**: Subcarpeta relativa (ej: '/' raíz, '/2024/Enero' subcarpeta)
    - **files**: Los archivos a subir (multipart/form-data)
    """
    await check_folder_access(area=area, subpath=subpath, required_access="upload", current_user=current_user, db=db)

    safe_subpath = subpath.strip("/")
    ruta_destino = os.path.join(BASE_DIR, area.upper(), safe_subpath) if safe_subpath else os.path.join(BASE_DIR, area.upper())

    if not os.path.isdir(ruta_destino):
        raise HTTPException(status_code=404, detail=f"La carpeta de destino no existe: /{area.upper()}/{safe_subpath}")

    uploaded_files = []
    failed_files = []

    CHUNK_SIZE = 1024 * 1024  # 1 MB por chunk

    for file in files:
        if ".." in subpath or ".." in (file.filename or ""):
            failed_files.append({"filename": file.filename, "error": "Ruta o nombre de archivo inválido"})
            continue

        safe_filename = os.path.basename(file.filename or "archivo_sin_nombre")
        if not safe_filename:
            failed_files.append({"filename": file.filename, "error": "Nombre de archivo inválido"})
            continue

        ruta_archivo = os.path.join(ruta_destino, safe_filename)
        if os.path.exists(ruta_archivo):
            failed_files.append({"filename": safe_filename, "error": "Ya existe un archivo con ese nombre"})
            continue

        try:
            with open(ruta_archivo, "wb") as f:
                while chunk := await file.read(CHUNK_SIZE):
                    f.write(chunk)

            size_bytes = os.path.getsize(ruta_archivo)
            size_kb = size_bytes / 1024
            size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
            ruta_logica = f"/{area.upper()}/{safe_subpath}/{safe_filename}".replace("//", "/")

            uploaded_files.append({
                "filename": safe_filename,
                "size": size_str,
                "path": ruta_logica
            })
        except PermissionError:
            failed_files.append({"filename": safe_filename, "error": "El servidor rechazó el permiso de escritura"})
        except OSError as e:
            failed_files.append({"filename": safe_filename, "error": f"Error del sistema: {e}"})
        finally:
            await file.close()

    return {
        "message": "Proceso de subida finalizado",
        "uploaded": uploaded_files,
        "failed": failed_files
    }
