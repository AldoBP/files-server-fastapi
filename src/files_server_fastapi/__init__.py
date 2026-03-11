# files_server_fastapi/__init__.py
# Exporta todos los routers para que main.py pueda importarlos directamente.

from files_server_fastapi.routers import (
    area_router,
    rol_router,
    rutas_router,
    permisos_router,
    users_extend_router,
    files_router,
)

__all__ = [
    "area_router",
    "rol_router",
    "rutas_router",
    "permisos_router",
    "users_extend_router",
    "files_router",
]
