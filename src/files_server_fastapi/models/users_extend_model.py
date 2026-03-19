from sqlmodel import Field
from oauth2fast_fastapi import BasicAuthModel


class Users_extend(BasicAuthModel, table=True):
    __tablename__ = "users_extend"

    # Es Primary Key y Foreign Key al mismo tiempo (Relación 1 a 1)
    user_id: int = Field(primary_key=True, foreign_key="users.id")

    area_id: int = Field(foreign_key="area.id")
    rol_id: int = Field(foreign_key="rol.id")
