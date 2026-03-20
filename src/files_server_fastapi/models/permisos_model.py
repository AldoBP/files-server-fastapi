from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel

# Catálogo principal de permisos
class Permisos(AuthModel, table=True):
    __tablename__ = "permisos"
    
    permiso_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)


# Tabla ACL: Control de Acceso Granular por Usuario a una Ruta
class User_Ruta_Access(AuthModel, table=True):
    __tablename__ = "user_ruta_access"
    
    user_id: int = Field(foreign_key="users.id")
    ruta_id: int = Field(foreign_key="rutas.id")
    
    # access_type puede ser: "allow_read", "allow_write", "deny_all"
    access_type: str = Field(nullable=False)


# Tabla intermedia: Permisos por Rol
class Permiso_rol(AuthModel, table=True):
    __tablename__ = "permiso_rol"
    
    id_rol: int = Field(foreign_key="rol.id")
    id_permiso: int = Field(foreign_key="permisos.id")
    ruta_id: int = Field(foreign_key="rutas.id")
