from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from database.db_enum import DocumentAvailability, IngestionStatus


class DocumentUpdateRequest(BaseModel):
    document_name: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    availability_status: Optional[DocumentAvailability] = None
    tags: Optional[list[str]] = None


class DocumentResponse(BaseModel):
    id: int
    document_name: str
    description: Optional[str] = None
    file_name: str
    extension: str
    category_id: int
    category_name: str
    user_id: int
    version: int
    status: IngestionStatus
    availability_status: DocumentAvailability
    tags: list[str] = []
    url: str
    created_at: datetime

    class Config:
        from_attributes = True
            


class DocumentListResponse(BaseModel):
    page: int
    limit: int
    total_pages: int
    total: int
    data: list[DocumentResponse]