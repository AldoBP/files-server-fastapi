from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy import DateTime as SADateTime
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class Area(AuthModel, table=True):
    __tablename__ = "area"

    area_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)

    # ── Soft Delete ───────────────────────────────────────────────────────────
    # NULL  → área activa
    # NOT NULL → área dada de baja (fecha/hora exacta de la baja)
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(SADateTime(timezone=True), nullable=True)
    )

    # ID del superadmin que ejecutó la baja. NULL si está activa.
    deleted_by: Optional[int] = Field(default=None, foreign_key="users.id")
