from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class Rol(AuthModel, table=True):
    __tablename__ = "rol"

    role_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
