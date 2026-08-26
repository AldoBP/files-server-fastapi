from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel

# Catálogo principal de permisos
class Permisos(AuthModel, table=True):
    __tablename__ = "permisos"
    
    permiso_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
    linux_acl: str = Field(default="---", description="Ejemplo: rwx, r-x, ---")
    fastapi_action: str = Field(default="deny_all", description="Ejemplo: web_view, web_edit, web_upload, web_full, deny_all")


# Tabla ACL: Control de Acceso Granular por Usuario a una Ruta
class User_Ruta_Access(AuthModel, table=True):
    __tablename__ = "user_ruta_access"
    
    user_id: int = Field(foreign_key="users.id")
    ruta_id: int = Field(foreign_key="rutas.id")
    
    # access_type puede ser: "web_view", "web_edit", "web_upload", "web_full", "deny_all"
    access_type: str = Field(nullable=False)

