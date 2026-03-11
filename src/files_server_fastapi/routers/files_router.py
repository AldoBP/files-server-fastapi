import os
from fastapi import APIRouter, HTTPException
from datetime import datetime
from pydantic import BaseModel

router = APIRouter(prefix="/files", tags=["Archivos del Sistema"])

# Directorio maestro (La ruta de red de Samba vista desde Windows)
BASE_DIR = r"\\192.168.1.122\Compartido"

@router.get("/list", summary="Listar archivos de una carpeta")
async def list_directory(area: str, subpath: str = "/"):
    # Seguridad básica: Evitar que un hacker suba de nivel con "../"
    if ".." in subpath:
        raise HTTPException(status_code=400, detail="Ruta inválida")
        
    safe_subpath = subpath.strip("/")
    
    if safe_subpath == "":
        ruta_real = os.path.join(BASE_DIR, area.upper())
    else:
        ruta_real = os.path.join(BASE_DIR, area.upper(), safe_subpath)
    
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
                    items.append({
                        "name": fichero.name,
                        "type": "folder",
                        "updated": fecha_mod,
                        "size": "",
                        "locked": False
                    })
                else:
                    size_kb = info.st_size / 1024
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
                    items.append({
                        "name": fichero.name,
                        "type": "file",
                        "updated": fecha_mod,
                        "size": size_str,
                        "locked": False
                    })
        
        items.sort(key=lambda x: (x["type"] == "file", x["name"].lower()))
        return items
        
    except PermissionError:
        raise HTTPException(status_code=403, detail="Acceso denegado por el sistema operativo")


# ==========================================
# RUTAS: CREAR CARPETAS
# ==========================================

class FolderCreate(BaseModel):
    area: str
    subpath: str
    folder_name: str

@router.post("/folder", summary="Crear una nueva carpeta en el servidor")
async def create_folder(req: FolderCreate):
    if ".." in req.subpath or ".." in req.folder_name or "/" in req.folder_name:
        raise HTTPException(status_code=400, detail="Nombre de carpeta o ruta inválida")

    safe_subpath = req.subpath.strip("/")
    
    if safe_subpath == "":
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), req.folder_name)
    else:
        ruta_final = os.path.join(BASE_DIR, req.area.upper(), safe_subpath, req.folder_name)

    try:
        os.makedirs(ruta_final, exist_ok=False)
        return {"message": "Carpeta creada exitosamente", "path": ruta_final}
    except FileExistsError:
        raise HTTPException(status_code=400, detail="Ya existe una carpeta con ese nombre aquí")
    except PermissionError:
        raise HTTPException(status_code=403, detail="El servidor rechazó el permiso de escritura")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# RUTA: ESCANEAR EL ÁRBOL DE CARPETAS
# ==========================================

def get_directory_tree(path_to_scan, base_name=""):
    """Función recursiva de Python para leer subcarpetas"""
    tree = []
    try:
        with os.scandir(path_to_scan) as entries:
            for entry in entries:
                if entry.is_dir():
                    relative_path = os.path.join(base_name, entry.name).replace("\\", "/")
                    tree.append({
                        "name": entry.name,
                        "path": f"/{relative_path}",
                        "children": get_directory_tree(entry.path, relative_path)
                    })
    except PermissionError:
        pass
    return sorted(tree, key=lambda x: x["name"].lower())

@router.get("/tree", summary="Obtener el árbol de carpetas de un área")
async def get_area_tree(area: str):
    area_path = os.path.join(BASE_DIR, area.upper())
    
    if not os.path.exists(area_path):
        return []

    return get_directory_tree(area_path)
