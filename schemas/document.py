from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from database.db_enum import IngestionStatus


class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = None
    category_id: Optional[int] = None


class DocumentResponse(BaseModel):
    id: int
    title: str
    file_name: str
    extension: str
    category_id: int
    category_name: str
    user_id: int
    version: int
    status: IngestionStatus
    created_at: datetime

    class Config:
        from_attributes = True
