from datetime import datetime, timezone
from sqlalchemy import Column, UniqueConstraint
from sqlalchemy import DateTime as SADateTime
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel


class UserFileAccess(AuthModel, table=True):
    __tablename__ = "user_file_access"
    __table_args__ = (
        UniqueConstraint("user_id", "area", "subpath", "filename", name="uq_user_file_access"),
    )

    user_id: int = Field(foreign_key="users.id", index=True)
    area: str = Field(nullable=False)
    subpath: str = Field(nullable=False)
    filename: str = Field(nullable=False)
    
    accessed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(SADateTime(timezone=True), nullable=False)
    )
