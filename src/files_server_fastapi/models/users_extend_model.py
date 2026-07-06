from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy import DateTime as SADateTime
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class Users_extend(AuthModel, table=True):
    __tablename__ = "users_extend"

    # Es Foreign Key al usuario (Relación 1 a 1)
    user_id: int = Field(foreign_key="users.id", unique=True)

    area_id: int = Field(foreign_key="area.id")
    rol_id: int = Field(foreign_key="rol.id")
    puesto: Optional[str] = Field(default=None)

    # Contraseña en texto plano para sincronización con el sistema de archivos centralizado de red
    samba_password: Optional[str] = Field(default=None)

    # Indica si el usuario tiene acceso Samba activado manualmente por el administrador.
    # Cuando es True, los permisos web se replican automáticamente a Linux ACLs / Samba.
    samba_enabled: bool = Field(default=False)

    # ── Soft Delete ───────────────────────────────────────────────────────────
    # NULL  → usuario activo
    # NOT NULL → usuario dado de baja (fecha/hora exacta de la baja)
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(SADateTime(timezone=True), nullable=True)
    )

    # ID del usuario (admin/sistemas) que ejecutó la baja. NULL si está activo.
    deleted_by: Optional[int] = Field(default=None, foreign_key="users.id")
