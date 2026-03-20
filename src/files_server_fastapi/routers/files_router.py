import os
import mimetypes
from fastapi.responses import FileResponse
from typing import Annotated
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from datetime import datetime
from pydantic import BaseModel
from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import get_current_user, User
from files_server_fastapi.models.permisos_model import User_Ruta_Access
from files_server_fastapi.models.rutas_model import Rutas
from files_server_fastapi.models.users_extend_model import Users_extend
from files_server_fastapi.models.area_model import Area
from files_server_fastapi.models.rol_model import Rol

router = APIRouter(prefix="/files", tags=["Archivos del Sistema"])

# ==========================================
# RUTINA DE VALIDACIÓN DE PERMISOS (ACL)
# ==========================================
async def check_folder_access(
    area: str,
    subpath: str = "/",
    required_access: str = "allow_read",
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Verifica si el usuario actual tiene acceso al área y subpath indicados.
    required_access: 'allow_read' (por defecto) o 'allow_write'
    """
    # 1. Obtener la jerarquía Area -> Rol del usuario
    result_ext = await db.execute(
        select(Users_extend)
        .where(Users_extend.user_id == current_user.id)
    )
    user_exts = result_ext.scalars().all()
    
    # Buscar si tiene acceso al área solicitada
    area_obj = None
    user_ext_match = None
    for ext in user_exts:
        res_area = await db.execute(select(Area).where(Area.id == ext.area_id))
        a = res_area.scalars().first()
        if a and a.area_name.upper() == area.upper():
            area_obj = a
            user_ext_match = ext
            break
            
    if not area_obj or not user_ext_match:
        raise HTTPException(status_code=403, detail="No perteneces a esta área")
        
    # Obtener su Rol Base en esta área
    res_rol = await db.execute(select(Rol).where(Rol.id == user_ext_match.rol_id))
    rol_obj = res_rol.scalars().first()
    rol_name = rol_obj.role_name.lower() if rol_obj else ""
    
    # 2. Verificar ACL específico para la ruta y sus padres (Herencia)
    # Construir la ruta lógica para buscar en BD
    logical_path = f"/{area.upper()}/{subpath.strip('/')}".replace("//", "/")
    
    # Generar todos los paths desde el más profundo hasta el superior
    # Ej: /AREA/FOLDER/SUB -> ['/AREA/FOLDER/SUB', '/AREA/FOLDER', '/AREA']
    parts = logical_path.strip("/").split("/")
    paths_to_check = []
    current_path = ""
    for part in parts:
        if part:
            current_path += f"/{part}"
            paths_to_check.append(current_path)
            
    # Ordenar del más largo al más corto para evaluar el más específico primero
    paths_to_check.reverse()
    
    # Obtener todas las rutas y posibles excepciones en una sola consulta
    res_acl = await db.execute(
        select(Rutas.ruta, User_Ruta_Access)
        .join(User_Ruta_Access, User_Ruta_Access.ruta_id == Rutas.id)
        .where(Rutas.ruta.in_(paths_to_check))
        .where(User_Ruta_Access.user_id == current_user.id)
    )
    acls_encontrados = {row[0]: row[1] for row in res_acl.all()}
    
    for path_in_tree in paths_to_check:
        if path_in_tree in acls_encontrados:
            acl_obj = acls_encontrados[path_in_tree]
            
            if acl_obj.access_type == "deny_all":
                raise HTTPException(status_code=403, detail="Acceso denegado a esta carpeta o heredado de una superior")
                
            if required_access == "allow_write":
                if acl_obj.access_type == "allow_write":
                    return True # Excepción le permite escribir
                elif acl_obj.access_type == "allow_read":
                    raise HTTPException(status_code=403, detail="Solo tienes permiso de lectura (regla heredada)")
                    
            if required_access == "allow_read":
                if acl_obj.access_type in ["allow_read", "allow_write"]:
                    return True
    
    # 3. Si no hay excepción ACL, aplicar reglas de Rol Base
    if required_access == "allow_write":
        if "editor" not in rol_name and "admin" not in rol_name:
            raise HTTPException(status_code=403, detail="Tu rol no permite modificar esta carpeta")
            
    # Si es allow_read, cualquier rol del área (viewer, editor, admin) puede leer por defecto
    return True


# Directorio maestro (La ruta de red de Samba vista desde Windows)
BASE_DIR = r"\\192.168.1.122\Compartido"


# ==========================================
# RUTA: LISTAR ARCHIVOS
# ==========================================

@router.get("/list", summary="Listar archivos de una carpeta")
async def list_directory(
    area: str, 
    subpath: str = "/", 
    has_access: bool = Depends(check_folder_access)
):
    """Devuelve el contenido de una carpeta dentro del area indicada."""
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
                    size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
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
# RUTA: CREAR CARPETAS
# ==========================================

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
    # Validar permisos de escritura manualmente ya que los argumentos vienen en el body
    await check_folder_access(area=req.area, subpath=req.subpath, required_access="allow_write", current_user=current_user, db=db)
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
# RUTA: SUBIR ARCHIVOS
# ==========================================

from fastapi import UploadFile, File, Form


@router.post("/upload", summary="Subir un archivo a una carpeta del servidor")
async def upload_file(
    area: str = Form(...),
    subpath: str = Form(default="/"),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session)
):
    # Validar permisos de escritura
    await check_folder_access(area=area, subpath=subpath, required_access="allow_write", current_user=current_user, db=db)
    """
    Sube un archivo (Word, PDF, imagen, etc.) a la carpeta indicada dentro del share Samba.

    - **area**: Área destino (ej: 'CONTABILIDAD')
    - **subpath**: Subcarpeta relativa dentro del área (ej: '/' para la raíz, '/2024/Enero' para subcarpeta)
    - **file**: El archivo a subir (multipart/form-data)
    """
    # Seguridad: Evitar path traversal
    if ".." in subpath or ".." in (file.filename or ""):
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    # Sanitizar nombre de archivo
    safe_filename = os.path.basename(file.filename or "archivo_sin_nombre")
    if not safe_filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido")

    safe_subpath = subpath.strip("/")

    if safe_subpath == "":
        ruta_destino = os.path.join(BASE_DIR, area.upper())
    else:
        ruta_destino = os.path.join(BASE_DIR, area.upper(), safe_subpath)

    # Verificar que la carpeta destino existe
    if not os.path.isdir(ruta_destino):
        raise HTTPException(
            status_code=404,
            detail=f"La carpeta de destino no existe: /{area.upper()}/{safe_subpath}"
        )

    ruta_archivo = os.path.join(ruta_destino, safe_filename)

    # No sobreescribir archivos existentes
    if os.path.exists(ruta_archivo):
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe un archivo con ese nombre en esta carpeta: {safe_filename}"
        )

    try:
        # Escritura por chunks — soporta archivos grandes sin agotar la RAM
        CHUNK_SIZE = 1024 * 1024  # 1 MB por chunk
        with open(ruta_archivo, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)

        # Calcular tamaño final
        size_bytes = os.path.getsize(ruta_archivo)
        size_kb = size_bytes / 1024
        size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"

        ruta_logica = f"/{area.upper()}/{safe_subpath}/{safe_filename}".replace("//", "/")

        return {
            "message": "Archivo subido exitosamente",
            "filename": safe_filename,
            "size": size_str,
            "path": ruta_logica,
        }

    except PermissionError:
        raise HTTPException(
            status_code=403,
            detail="El servidor rechazó el permiso de escritura en el share Samba"
        )
    except OSError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error del sistema al guardar el archivo: {e}"
        )
    finally:
        await file.close()


# ==========================================
# RUTA: OBTENER URL PARA ABRIR ARCHIVO EN OFFICE LOCAL
# ==========================================

# Mapeo extensión → protocolo de Office
OFFICE_PROTOCOLS = {
    "doc":  "ms-word",
    "docx": "ms-word",
    "dot":  "ms-word",
    "dotx": "ms-word",
    "xls":  "ms-excel",
    "xlsx": "ms-excel",
    "xlsm": "ms-excel",
    "ppt":  "ms-powerpoint",
    "pptx": "ms-powerpoint",
    "pps":  "ms-powerpoint",
    "ppsx": "ms-powerpoint",
}


@router.get("/open-url", summary="Obtener URL para abrir un archivo en la app local (Office, etc.)")
async def get_open_url(
    area: str, 
    filename: str, 
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access)
):
    """
    Devuelve la URL de protocolo adecuada para abrir el archivo directamente
    en la aplicación instalada en la PC del usuario.

    - Archivos **Office** (.docx, .xlsx, .pptx, etc.): devuelve una URL `ms-word:...` /
      `ms-excel:...` / `ms-powerpoint:...` que abre el archivo directo desde el share Samba
      y permite guardar de vuelta sin descargar.
    - **Otros archivos** (PDF, imágenes, txt): devuelve la URL del endpoint `/files/download`
      para que el navegador los muestre inline.
    """
    if ".." in subpath or ".." in filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    safe_filename = os.path.basename(filename)
    safe_subpath = subpath.strip("/")

    # Construir la ruta UNC real para verificar que el archivo existe
    if safe_subpath == "":
        ruta_real = os.path.join(BASE_DIR, area.upper(), safe_filename)
    else:
        ruta_real = os.path.join(BASE_DIR, area.upper(), safe_subpath, safe_filename)

    if not os.path.isfile(ruta_real):
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {safe_filename}")

    # Determinar tipo de archivo por extensión
    ext = safe_filename.rsplit(".", 1)[-1].lower() if "." in safe_filename else ""
    office_protocol = OFFICE_PROTOCOLS.get(ext)

    if office_protocol:
        # Construir ruta UNC para el protocolo de Office
        # El protocolo necesita la ruta absoluta del share Samba
        if safe_subpath == "":
            unc_path = f"{BASE_DIR}\\{area.upper()}\\{safe_filename}"
        else:
            subpath_win = safe_subpath.replace("/", "\\")
            unc_path = f"{BASE_DIR}\\{area.upper()}\\{subpath_win}\\{safe_filename}"

        # Formato estándar del protocolo de Office:
        # ms-word:ofe|u|\\servidor\share\ruta\archivo.docx
        office_url = f"{office_protocol}:ofe|u|{unc_path}"

        return {
            "type": "office",
            "protocol": office_protocol,
            "url": office_url,
            "unc_path": unc_path,
            "filename": safe_filename,
        }
    else:
        # Para PDFs, imágenes, txt → usar endpoint de descarga/vista inline
        return {
            "type": "download",
            "url": f"/files/download?area={area}&subpath={subpath}&filename={safe_filename}",
            "filename": safe_filename,
        }


# ==========================================
# RUTA: DESCARGAR / VER ARCHIVO INLINE
# ==========================================

# MIME types que el navegador sabe mostrar inline (sin descarga forzada)
INLINE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml",
    "text/plain", "text/csv", "text/html",
}


@router.get("/download", summary="Descargar o visualizar un archivo inline en el navegador")
async def download_file(
    area: str, 
    filename: str, 
    subpath: str = "/",
    has_access: bool = Depends(check_folder_access)
):
    """
    Sirve un archivo desde el share Samba.
    - PDFs e imágenes se abren **inline** en el navegador.
    - Otros tipos de archivo se descargan.
    """
    if ".." in subpath or ".." in filename:
        raise HTTPException(status_code=400, detail="Ruta o nombre de archivo inválido")

    safe_filename = os.path.basename(filename)
    safe_subpath = subpath.strip("/")

    if safe_subpath == "":
        ruta_real = os.path.join(BASE_DIR, area.upper(), safe_filename)
    else:
        ruta_real = os.path.join(BASE_DIR, area.upper(), safe_subpath, safe_filename)

    if not os.path.isfile(ruta_real):
        raise HTTPException(status_code=404, detail=f"Archivo no encontrado: {safe_filename}")

    # Detectar MIME type
    mime_type, _ = mimetypes.guess_type(safe_filename)
    mime_type = mime_type or "application/octet-stream"

    # Si el navegador puede mostrarlo, enviarlo inline; si no, como attachment
    disposition = "inline" if mime_type in INLINE_MIME_TYPES else "attachment"

    return FileResponse(
        path=ruta_real,
        media_type=mime_type,
        filename=safe_filename,
        headers={
            "Content-Disposition": f'{disposition}; filename="{safe_filename}"',
            "Cache-Control": "no-cache",
        },
    )


# ==========================================
# RUTA: ESCANEAR EL ÁRBOL DE CARPETAS
# ==========================================

def get_directory_tree(path_to_scan, base_name=""):
    """Función recursiva para leer el árbol de subcarpetas."""
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
