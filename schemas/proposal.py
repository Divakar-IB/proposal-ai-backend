from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from database.db_enum import ProposalSectionStatus, ProposalStatus


class ProposalGenerateRequest(BaseModel):
    requirement_document_id: int
    category_ids: Optional[list[int]] = None


class ProposalSectionResponse(BaseModel):
    id: int
    section_key: str
    order_index: int
    content: Optional[str] = None
    sources: Optional[list[dict[str, Any]]] = None
    status: ProposalSectionStatus
    confidence_score: Optional[float] = None
    review_flag: bool = False

    class Config:
        from_attributes = True


class SectionEditRequest(BaseModel):
    content: str


class ProposalResponse(BaseModel):
    id: int
    requirement_document_id: int
    user_id: int
    title: str
    status: ProposalStatus
    markdown_path: Optional[str] = None
    docx_path: Optional[str] = None
    error_message: Optional[str] = None
    sections: list[ProposalSectionResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True
