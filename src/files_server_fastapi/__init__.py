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


def get_webdav_wsgi_app():
    """
    Crea y devuelve la aplicación WSGI WebDAV para montar en FastAPI.

    Uso en main.py:
        from starlette.middleware.wsgi import WSGIMiddleware
        from files_server_fastapi import get_webdav_wsgi_app

        webdav_app = get_webdav_wsgi_app()
        app.mount("/webdav", WSGIMiddleware(webdav_app))
    """
    from files_server_fastapi.files.webdav_setup import create_webdav_app
    from files_server_fastapi.files.constants import BASE_DIR
    return create_webdav_app(BASE_DIR)


__all__ = [
    "area_router",
    "rol_router",
    "rutas_router",
    "permisos_router",
    "users_extend_router",
    "files_router",
    "get_webdav_wsgi_app",
]
