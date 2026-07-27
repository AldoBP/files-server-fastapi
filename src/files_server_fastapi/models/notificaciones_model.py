from typing import Optional
from datetime import datetime
from sqlalchemy import Column, DateTime as SADateTime, Boolean, Text
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class Notificacion(AuthModel, table=True):
    __tablename__ = "notificaciones"

    # Usuario destinatario de la notificación
    user_id: int = Field(foreign_key="users.id", index=True)

    # Tipo de evento — permite filtrar y escalar a futuros eventos
    # Ejemplos: "acceso_carpeta", "revocacion_acceso", "alerta_area"
    tipo: str = Field(nullable=False, max_length=50)

    # Título corto (para mostrar en el badge/lista)
    titulo: str = Field(nullable=False, max_length=255)

    # Mensaje completo con contexto (quién compartió, qué carpeta, etc.)
    mensaje: str = Field(sa_column=Column(Text, nullable=False))

    # Estado de lectura
    leida: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, default=False),
    )

    # Timestamp de creación (UTC)
    created_at: datetime = Field(
        default_factory=lambda: datetime.utcnow(),
        sa_column=Column(SADateTime, nullable=False),
    )

    # Metadatos extra en JSON serializado (ruta_id, area, permiso, etc.)
    # Útil para que el frontend pueda navegar directamente a la carpeta compartida
    meta: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
