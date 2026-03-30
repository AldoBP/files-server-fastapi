import os
from fastapi import APIRouter
from files_server_fastapi.files.constants import BASE_DIR

router = APIRouter()


def get_directory_tree(path_to_scan: str, base_name: str = "") -> list:
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
