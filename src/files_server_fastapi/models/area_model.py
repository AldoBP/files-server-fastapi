from typing import Optional
from sqlmodel import Field
from oauth2fast_fastapi import AuthModel

class Area(AuthModel, table=True):
    __tablename__ = "area"

    area_name: str = Field(nullable=False)
    description: Optional[str] = Field(default=None)
