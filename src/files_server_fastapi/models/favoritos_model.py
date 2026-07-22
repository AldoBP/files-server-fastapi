from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class UserFavorito(AuthModel, table=True):
    """
    Accesos directos / Favoritos de carpetas por usuario.

    Cada registro vincula un usuario con una ruta (carpeta) que él mismo
    ha marcado como favorita. El alias le permite ponerle un nombre
    personalizado y el orden controla cómo aparecen en el sidebar.

    Restricción de seguridad:
        El endpoint de creación valida que la ruta pertenezca al área del
        usuario (o que el usuario tenga acceso explícito a ella), por lo que
        nunca se puede agregar como favorito algo a lo que no se tiene acceso.
    """
    __tablename__ = "user_favorito"

    # Usuario propietario del acceso directo
    user_id: int = Field(foreign_key="users.id")

    # Carpeta / sub-carpeta a la que apunta el acceso directo
    ruta_id: int = Field(foreign_key="rutas.id")

    # Nombre personalizado opcional (ej: "Facturas Ene 2026")
    # Si es None, el frontend usa el nombre original de la ruta
    alias: Optional[str] = Field(default=None, max_length=100)

    # Posición en el sidebar (0 = primero). Permite reordenar con drag & drop
    orden: int = Field(default=0)
