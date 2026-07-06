from typing import Optional
from datetime import datetime, timezone
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


def get_utc_now():
    return datetime.now(timezone.utc)


class Rol(AuthModel, table=True):
    __tablename__ = "rol"

    role_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)

    # Nivel de privilegio del rol. Desacopla la autorización del nombre del rol:
    # el nombre puede cambiar libremente sin afectar la lógica del sistema.
    #
    #   0 → Usuario regular     (sin permisos de gestión)
    #   1 → Admin de Área       (gestión de su propia área)
    #   2 → Superadmin/Sistemas (acceso total)
    #
    # Para agregar nuevos niveles en el futuro, solo actualiza este campo en la DB.
    privilege_level: int = Field(default=0, nullable=False)

