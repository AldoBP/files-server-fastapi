"""
path_utils.py — Utilidades para normalización de rutas lógicas.

Centraliza la lógica para evitar que las rutas guardadas en la
base de datos contengan áreas duplicadas o anidadas incorrectamente.
"""


def normalize_subpath(area: str, subpath: str) -> str:
    """
    Normaliza un subpath relativo eliminando cualquier prefijo de área
    que el frontend pudo haber enviado acumulado.

    Ejemplos:
      normalize_subpath("VENTAS", "/VENTAS/test1") -> "test1"
      normalize_subpath("VENTAS", "VENTAS/test1")  -> "test1"
      normalize_subpath("VENTAS", "test1/sub")     -> "test1/sub"
      normalize_subpath("VENTAS", "")              -> ""
    """
    area_upper = area.strip().upper()
    clean = subpath.strip("/")

    # Si el subpath empieza con el nombre del área, lo quitamos
    prefix_len: int = len(area_upper) + 1
    if clean.upper().startswith(area_upper + "/"):
        clean = clean[prefix_len:]
    elif clean.upper() == area_upper:
        clean = ""

    return clean.strip("/")


def build_logical_path(area: str, subpath: str, folder_name: str | None = None) -> str:
    """
    Construye la ruta lógica completa normalizada.

    Args:
        area:        Nombre del área (ej. "VENTAS")
        subpath:     Subpath relativo del frontend (puede traer el área como prefijo)
        folder_name: Nombre de la carpeta nueva (opcional, para creación de carpeta)

    Returns:
        Ruta lógica limpia, ej: "/VENTAS/test1/nueva"
    """
    area_upper = area.strip().upper()
    clean_sub = normalize_subpath(area_upper, subpath)

    parts = [p for p in [area_upper, clean_sub, folder_name] if p]
    return "/" + "/".join(parts)
