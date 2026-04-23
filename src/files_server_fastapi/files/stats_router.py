import os
import shutil
import asyncio
from fastapi import APIRouter, HTTPException, Depends
from files_server_fastapi.files.constants import BASE_DIR
from files_server_fastapi.files.dependencies import check_folder_access

router = APIRouter()


def _compute_stats(ruta_real: str) -> dict:
    """Función síncrona que hace el os.walk (se ejecuta en un thread separado)."""
    total_files = 0
    total_folders = 0
    total_size = 0
    recent_files = []

    try:
        for root, dirs, files in os.walk(ruta_real):
            # Filtrar carpetas ocultas (que empiezan con .)
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            total_folders += len(dirs)
            total_files += len(files)
            for f in files:
                try:
                    fp = os.path.join(root, f)
                    if not os.path.islink(fp):
                        st = os.stat(fp)
                        total_size += st.st_size
                        recent_files.append((st.st_mtime, f, root))
                except OSError:
                    pass
    except PermissionError:
        pass

    # Top 5 archivos modificados recientemente
    recent_files.sort(reverse=True)
    top_recent = [
        {"name": name, "folder": folder.replace(ruta_real, "").lstrip("/") or "/"}
        for _, name, folder in recent_files[:5]
    ]

    # Formato legible del tamaño usado por el Área
    def format_size(size_bytes):
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / 1024 ** 2:.1f} MB"
        elif size_bytes < 1024 ** 4:
            return f"{size_bytes / 1024 ** 3:.2f} GB"
        else:
            return f"{size_bytes / 1024 ** 4:.2f} TB"
    size_str = format_size(total_size)
    
    # NUEVO: Lógica dinámica de espacio del disco total
    # Para sacar cuál es el espacio máximo que puede ocupar (Tomamos el disco root de ruta_real)
    try:
        usage = shutil.disk_usage(ruta_real)
        total_disk_bytes = usage.total
        total_str = format_size(total_disk_bytes)
        # El porcentaje de uso de esta área respecto al disco total
        percent_used = round((total_size / total_disk_bytes) * 100, 2)
    except Exception:
         # Fallback en caso de que ocurra algún error 
        total_disk_bytes = 0
        total_str = None
        percent_used = 0

    return {
        "files": total_files,
        "folders": total_folders,
        "sizeBytes": total_size,
        "sizeStr": size_str,
        "recentFiles": top_recent,
        "totalBytes": total_disk_bytes,      # <--- Lo añadimos
        "totalStr": total_str,               # <--- Lo añadimos (ej. "924.3 GB")
        "percentUsed": percent_used          # <--- Lo añadimos
    }


@router.get("/stats", summary="Estadísticas de almacenamiento de un área")
async def get_area_stats(
    area: str,
    has_access: bool = Depends(check_folder_access),
):
    """
    Devuelve estadísticas del área completa:
    - Número de carpetas y archivos
    - Espacio total ocupado
    - Los 5 archivos modificados más recientemente

    Solo los usuarios con acceso al área pueden consultarlo.
    """
    ruta_real = os.path.join(BASE_DIR, area.upper())

    if not os.path.exists(ruta_real):
        return {
            "files": 0,
            "folders": 0,
            "sizeBytes": 0,
            "sizeStr": "0 B",
            "recentFiles": [],
            "area": area.upper(),
        }

    # Ejecuta el os.walk en un thread separado para no bloquear el event loop
    stats = await asyncio.to_thread(_compute_stats, ruta_real)
    stats["area"] = area.upper()
    return stats


@router.get("/stats/server", summary="Estadísticas de almacenamiento total del servidor")
async def get_server_stats():
    """
    Devuelve las estadísticas generales del disco donde se encuentra BASE_DIR:
    - Espacio total
    - Espacio usado
    - Espacio libre
    """
    try:
        usage = shutil.disk_usage(BASE_DIR)

        def format_size(size_bytes):
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 ** 2:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 ** 3:
                return f"{size_bytes / 1024 ** 2:.1f} MB"
            elif size_bytes < 1024 ** 4:
                return f"{size_bytes / 1024 ** 3:.2f} GB"
            else:
                return f"{size_bytes / 1024 ** 4:.2f} TB"

        return {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "totalStr": format_size(usage.total),
            "usedStr": format_size(usage.used),
            "freeStr": format_size(usage.free),
            "percentUsed": round((usage.used / usage.total) * 100, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error obteniendo estadísticas del disco: {str(e)}")
