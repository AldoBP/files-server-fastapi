from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel

# Catálogo principal de permisos
class Permisos(AuthModel, table=True):
    __tablename__ = "permisos"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    permiso_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)


# Tabla intermedia: Permisos por Usuario
class Permiso_user(AuthModel, table=True):
    __tablename__ = "permiso_user"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    id_user: int = Field(foreign_key="users.id")
    id_permiso: int = Field(foreign_key="permisos.id")
    ruta_id: int = Field(foreign_key="rutas.id")


# Tabla intermedia: Permisos por Rol
class Permiso_rol(AuthModel, table=True):
    __tablename__ = "permiso_rol"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    id_rol: int = Field(foreign_key="rol.id")
    id_permiso: int = Field(foreign_key="permisos.id")
    ruta_id: int = Field(foreign_key="rutas.id")
