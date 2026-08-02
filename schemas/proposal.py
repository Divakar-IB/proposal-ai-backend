from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from database.db_enum import GenerationMode, ProposalSectionStatus, ProposalStatus
from generation.length_budget import MIN_PROPOSAL_PAGES
from rendering.html_templates import DEFAULT_TEMPLATE_ID
from schemas.requirement_document import (
    CapabilityTagOut,
    KnowledgeMatch,
    RequirementDocumentResponse,
)


class ProposalGenerateRequest(BaseModel):
    proposal_id: int
    # Every section in SECTION_DEFINITIONS is always generated, so a page count
    # below the minimum cannot fit their required subsection outlines — see
    # generation/length_budget.py. Rejected here (422) rather than silently
    # producing a proposal that overruns the requested length.
    page_count: int = Field(
        ge=MIN_PROPOSAL_PAGES,
        description=f"Target page count for the generated proposal (minimum {MIN_PROPOSAL_PAGES}).",
    )
    generation_mode: GenerationMode


class ProposalSectionResponse(BaseModel):
    id: int
    section_key: str
    title: str
    order_index: int
    content: Optional[str] = None
    sources: Optional[list[dict[str, Any]]] = None
    status: ProposalSectionStatus

    class Config:
        from_attributes = True


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


class ProposalStatsResponse(BaseModel):
    total: int
    inprogress: int
    generating: int
    review: int
    done: int
    failed: int


class ExportFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class ProposalExportRequest(BaseModel):
    # Defaults to the Professional template — the only one whose DOCX export is
    # style-matched to its PDF (see rendering/html_templates.DOCX_REFERENCES).
    template_id: int = DEFAULT_TEMPLATE_ID
    format: ExportFormat


class ProposalExportEmailRequest(BaseModel):
    template_id: int = DEFAULT_TEMPLATE_ID
    format: ExportFormat
    email: EmailStr


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
