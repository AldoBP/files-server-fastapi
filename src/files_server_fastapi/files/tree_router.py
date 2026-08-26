import os
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from pgsqlasync2fast_fastapi.dependencies import get_db_session
from oauth2fast_fastapi import User
from files_server_fastapi.dependencies.user_dependencies import get_active_user
from files_server_fastapi.files.constants import BASE_DIR

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helpers síncronos (se ejecutan en un thread pool) ─────────────────────────

def _scan_one_level(physical_path: str) -> list[dict]:
    """
    Escanea UNA sola capa de directorios y devuelve una lista con:
      - name: nombre de la carpeta
      - path: ruta relativa (empezando con "/")
      - has_children: bool que indica si contiene al menos una subcarpeta

    Se ejecuta en un thread pool para no bloquear el event loop de FastAPI.
    """
    result: list[dict] = []

    try:
        entries = sorted(os.scandir(physical_path), key=lambda e: e.name.lower())
    except PermissionError:
        return result

    for entry in entries:
        if not entry.is_dir():
            continue

        # Calcular ruta relativa al directorio del área
        # physical_path = BASE_DIR/AREA[/sub/path]
        # Queremos el path relativo dentro del área → quitar BASE_DIR del prefix
        try:
            rel = os.path.relpath(entry.path, BASE_DIR)   # p.e. "VENTAS/2026/Enero"
            # Convertir separadores de OS a "/" y asegurarse de que inicie con "/"
            rel_posix = "/" + rel.replace(os.sep, "/")
        except ValueError:
            # En Windows si están en unidades distintas (improbable en Linux)
            rel_posix = "/" + entry.name

        # Verificar si tiene al menos una subcarpeta directa
        has_children = False
        try:
            for sub in os.scandir(entry.path):
                if sub.is_dir():
                    has_children = True
                    break
        except PermissionError:
            has_children = False

        result.append({
            "name": entry.name,
            "path": rel_posix,
            "has_children": has_children,
        })

    return result


def _get_directory_tree(path_to_scan: str, base_name: str = "") -> list:
    """Función recursiva original — usada por el endpoint legacy /tree."""
    tree = []
    try:
        with os.scandir(path_to_scan) as entries:
            for entry in entries:
                if entry.is_dir():
                    relative_path = os.path.join(base_name, entry.name).replace("\\", "/")
                    tree.append({
                        "name": entry.name,
                        "path": f"/{relative_path}",
                        "children": _get_directory_tree(entry.path, relative_path),
                    })
    except PermissionError:
        pass
    return sorted(tree, key=lambda x: x["name"].lower())


# ── Endpoint legacy (se mantiene para retrocompatibilidad) ────────────────────

@router.get("/tree", summary="Obtener el árbol de carpetas de un área (recursivo)")
async def get_area_tree(area: str):
    """
    Devuelve el árbol completo de carpetas de un área de forma recursiva.

    ⚠️  Para áreas con muchas subcarpetas este endpoint puede ser lento.
    Preferir el nuevo endpoint /tree/children que implementa lazy loading.
    """
    area_path = os.path.join(BASE_DIR, area.upper())
    if not os.path.exists(area_path):
        return []
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_directory_tree, area_path)


# ── Nuevo endpoint con Lazy Loading ───────────────────────────────────────────

@router.get(
    "/tree/children",
    summary="Obtener hijos directos de una carpeta (Lazy Loading)",
)
async def get_folder_children(
    area: str,
    path: str = "/",
    current_user: User = Depends(get_active_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Devuelve **solo los subdirectorios inmediatos** (un nivel) de la carpeta indicada.

    Parámetros:
    - **area**: nombre del área (ej. `SISTEMAS`, `VENTAS`). Se normaliza a mayúsculas.
    - **path**: ruta relativa dentro del área (ej. `/` para la raíz, `/2026/Enero`).
               Por defecto es `/` (raíz del área).

    Respuesta:
    ```json
    [
      { "name": "2026",     "path": "/VENTAS/2026",           "has_children": true  },
      { "name": "Reportes", "path": "/VENTAS/Reportes",       "has_children": false },
      ...
    ]
    ```

    - `has_children: true` → la carpeta contiene subcarpetas; el frontend debe mostrar `▶`.
    - `has_children: false` → es una hoja; el frontend puede mostrar `•` o ningún botón.

    El escaneo corre en un thread pool para no bloquear el event loop de FastAPI.
    """
    area_upper = area.strip().upper()

    # Normalizar el path: quitar barras dobles y barra final
    clean_path = path.strip("/")

    # Construir la ruta física en el sistema de archivos
    if clean_path:
        # Prevenir path traversal
        if ".." in clean_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ruta inválida.",
            )
        physical_path = os.path.join(BASE_DIR, area_upper, clean_path)
    else:
        physical_path = os.path.join(BASE_DIR, area_upper)

    if not os.path.isdir(physical_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La carpeta '{path}' no existe en el área '{area_upper}'.",
        )

    logger.debug(
        "tree/children area=%r path=%r → physical=%r user=%s",
        area_upper, path, physical_path, current_user.id,
    )

    # Ejecutar el escaneo en un thread pool para no bloquear el event loop
    loop = asyncio.get_event_loop()
    children = await loop.run_in_executor(None, _scan_one_level, physical_path)

    return children

