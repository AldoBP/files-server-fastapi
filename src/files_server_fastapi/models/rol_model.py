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
