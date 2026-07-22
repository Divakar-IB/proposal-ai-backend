from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus


class ProposalGenerateRequest(BaseModel):
    proposal_id: int
    page_count: int
    generation_mode: GenerationMode


class ProposalSectionResponse(BaseModel):
    id: int
    section_key: str
    title: str
    order_index: int
    content: Optional[str] = None
    sources: Optional[list[dict[str, Any]]] = None
    status: ProposalSectionStatus
    confidence_score: Optional[float] = None
    review_flag: bool = False

    class Config:
        from_attributes = True


class SectionEditItem(BaseModel):
    section_id: int
    content: str


class SectionsBulkEditRequest(BaseModel):
    sections: list[SectionEditItem]


class ProposalResponse(BaseModel):
    id: int
    requirement_document_ids: list[int] = []
    user_id: int
    title: str
    client_name: str
    additional_context: Optional[str] = None
    generation_mode: Optional[GenerationMode] = None
    page_count: Optional[int] = None
    status: ProposalStatus
    markdown_path: Optional[str] = None
    approved_markdown: Optional[str] = None
    docx_path: Optional[str] = None
    pdf_path: Optional[str] = None
    error_message: Optional[str] = None
    sections: list[ProposalSectionResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ProposalExportResponse(BaseModel):
    proposal_id: int
    status: ProposalStatus
    markdown_url: Optional[str] = None
    docx_url: Optional[str] = None
    pdf_url: Optional[str] = None
