import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


@router.get("/list", summary="Listar archivos de una carpeta")
async def list_directory(
    area: str,
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access)
):
    """Devuelve el contenido de una carpeta dentro del área indicada."""
    if ".." in subpath:
        raise HTTPException(status_code=400, detail="Ruta inválida")

    safe_subpath = subpath.strip("/")
    ruta_real = os.path.join(BASE_DIR, area.upper(), safe_subpath) if safe_subpath else os.path.join(BASE_DIR, area.upper())
    print(ruta_real)

    if not os.path.exists(ruta_real):
        return []
    if not os.path.isdir(ruta_real):
        raise HTTPException(status_code=400, detail="La ruta no es un directorio")

    items = []
    try:
        with os.scandir(ruta_real) as ficheros:
            for fichero in ficheros:
                info = fichero.stat()
                fecha_mod = datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M")
                if fichero.is_dir():
                    items.append({"name": fichero.name, "type": "folder", "updated": fecha_mod, "size": "", "locked": False})
                else:
                    size_kb = info.st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                    items.append({"name": fichero.name, "type": "file", "updated": fecha_mod, "size": size_str, "locked": False})

        items.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
        return items
    except PermissionError:
        raise HTTPException(status_code=403, detail="Acceso denegado por el sistema operativo")
