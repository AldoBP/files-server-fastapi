from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel

class Users_extend(AuthModel, table=True):
    __tablename__ = "users_extend"
    
    # Es Foreign Key al usuario (Relación 1 a 1)
    user_id: int = Field(foreign_key="users.id", unique=True)
    
    area_id: int = Field(foreign_key="area.id")
    rol_id: int = Field(foreign_key="rol.id")
    puesto: Optional[str] = Field(default=None)
