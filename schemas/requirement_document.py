from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from database.db_enum import DocumentStatus


class KnowledgeMatch(BaseModel):
    document_id: int
    title: str
    source_filename: str
    breadcrumb: str
    match_percent: int


class CapabilityTagOut(BaseModel):
    name: str
    confidence: float


class RequirementDocumentResponse(BaseModel):
    id: int
    proposal_id: int
    file_name: str
    extension: str
    user_id: int
    proposal_name: str
    client_name: str
    additional_context: Optional[str] = None
    status: DocumentStatus
    summary: Optional[str] = None
    knowledge_matches: list[KnowledgeMatch] = []
    capability_tags: list[CapabilityTagOut] = []
    created_at: datetime
    additional_documents: list["RequirementDocumentResponse"] = []

    class Config:
        from_attributes = True
