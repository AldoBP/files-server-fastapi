# models/__init__.py
from .area_model import Area
from .rol_model import Rol
from .rutas_model import Rutas
from .permisos_model import Permisos, User_Ruta_Access, Permiso_rol
from .users_extend_model import Users_extend

__all__ = [
    "Area",
    "Rol",
    "Rutas",
    "Permisos",
    "User_Ruta_Access",
    "Permiso_rol",
    "Users_extend",
]
