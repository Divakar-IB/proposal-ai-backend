from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from database.db_enum import DocumentStatus


class KnowledgeMatch(BaseModel):
    category_id: int
    category_name: str
    match_percent: int


class RequirementDocumentResponse(BaseModel):
    id: int
    file_name: str
    extension: str
    user_id: int
    status: DocumentStatus
    parsed_data: Optional[dict[str, Any]] = None
    summary: Optional[str] = None
    knowledge_matches: list[KnowledgeMatch] = []
    created_at: datetime

    class Config:
        from_attributes = True
