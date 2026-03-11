# routers/__init__.py
from files_server_fastapi.routers import area_router
from files_server_fastapi.routers import rol_router
from files_server_fastapi.routers import rutas_router
from files_server_fastapi.routers import permisos_router
from files_server_fastapi.routers import users_extend_router
from files_server_fastapi.routers import files_router

__all__ = [
    "area_router",
    "rol_router",
    "rutas_router",
    "permisos_router",
    "users_extend_router",
    "files_router",
]
