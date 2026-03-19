from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class Rutas(AuthModel, table=True):
    __tablename__ = "rutas"

    ruta: str = Field(nullable=False)
    name: str = Field(nullable=False)

    # Llave foránea hacia Area
    area_id: int = Field(foreign_key="area.id")

    # Auto-referencia para sub-rutas (puede ser nula si es ruta principal)
    ruta_id: Optional[int] = Field(default=None, foreign_key="rutas.id")
