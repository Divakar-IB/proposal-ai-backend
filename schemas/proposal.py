from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr

from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus
from schemas.requirement_document import (
    CapabilityTagOut,
    KnowledgeMatch,
    RequirementDocumentResponse,
)


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
    is_approved: bool = False
    approved_markdown: Optional[str] = None
    proposal_json: Optional[dict[str, Any]] = None
    docx_path: Optional[str] = None
    pdf_path: Optional[str] = None
    error_message: Optional[str] = None
    sections: list[ProposalSectionResponse] = []
    created_at: datetime

    class Config:
        from_attributes = True


class ProposalListResponse(BaseModel):
    page: int
    limit: int
    total_pages: int
    total: int
    data: list[ProposalResponse]


class ExportFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class ProposalExportRequest(BaseModel):
    template_id: int
    format: ExportFormat


class ProposalExportEmailResponse(BaseModel):
    proposal_id: int
    template_id: int
    format: ExportFormat
    sent_to: EmailStr
class ProposalSectionMinimal(BaseModel):
    id: int
    title: str
    content: Optional[str] = None
    order: int

    class Config:
        from_attributes = True


class ProposalSectionOrderItem(BaseModel):
    id: int
    order: int


class ProposalSectionsReorderRequest(BaseModel):
    sections: list[ProposalSectionOrderItem]


class ProposalDetailResponse(BaseModel):
    id: int
    title: str
    client_name: str
    status: ProposalStatus
    sections: list[ProposalSectionMinimal] = []

    class Config:
        from_attributes = True


class ProposalExportResponse(BaseModel):
    proposal_id: int
    status: ProposalStatus
    markdown_url: Optional[str] = None
    docx_url: Optional[str] = None
    pdf_url: Optional[str] = None


class ExportTemplateResponse(BaseModel):
    id: int
    name: str
    description: str
    preview_url: Optional[str] = None


class ProposalDetailsStep(BaseModel):
    proposal_name: str
    client_name: str
    additional_context: Optional[str] = None
    files: list[RequirementDocumentResponse] = []


class SummaryStep(BaseModel):
    summary: Optional[str] = None
    knowledge_matches: list[KnowledgeMatch] = []
    capability_tags: list[CapabilityTagOut] = []


class GenerationConfigStep(BaseModel):
    generation_mode: Optional[GenerationMode] = None
    page_count: Optional[int] = None


class GenerationStep(BaseModel):
    status: Literal["generating", "done", "failed"]


class ProposalStateResponse(BaseModel):
    proposal_id: int
    current_step: str
    proposal_details: Optional[ProposalDetailsStep] = None
    summary: Optional[SummaryStep] = None
    generation_config: Optional[GenerationConfigStep] = None
    generation: Optional[GenerationStep] = None
