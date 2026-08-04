from datetime import datetime

from pydantic import BaseModel

from database.db_enum import DocumentAvailability, IngestionStatus


class DocumentUpdateRequest(BaseModel):
    document_name: str | None = None
    description: str | None = None
    category_id: int | None = None
    availability_status: DocumentAvailability | None = None
    tags: list[str] | None = None


class DocumentResponse(BaseModel):
    id: int
    document_name: str
    description: str | None = None
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
