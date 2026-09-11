from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Column
from sqlalchemy import DateTime as SADateTime
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class UserTrash(AuthModel, table=True):
    __tablename__ = "user_trash"

    user_id: int = Field(foreign_key="users.id", index=True)
    area: str = Field(nullable=False)
    original_subpath: str = Field(nullable=False)
    filename: str = Field(nullable=False)
    trash_path: str = Field(nullable=False)
    item_type: str = Field(nullable=False)  # 'file' | 'folder'
    size_bytes: Optional[int] = Field(default=None)

    trashed_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(SADateTime(timezone=True), nullable=False)
    )
    # Usuario que movió a la papelera (por defecto, el mismo user_id)
    deleted_by: Optional[int] = Field(default=None, foreign_key="users.id")

    # NULL = en papelera; NOT NULL = eliminado definitivamente
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(SADateTime(timezone=True), nullable=True)
    )

    restored_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(SADateTime(timezone=True), nullable=True)
    )
    # Usuario que restauró de la papelera
    restored_by: Optional[int] = Field(default=None, foreign_key="users.id")
