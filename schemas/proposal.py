from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field

from database.db_enum import DocumentStatus, GenerationMode, ProposalSectionStatus, ProposalStatus
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
    content: str | None = None
    sources: list[dict[str, Any]] | None = None
    status: ProposalSectionStatus

    class Config:
        from_attributes = True


class ProposalResponse(BaseModel):
    id: int
    requirement_document_ids: list[int] = []
    user_id: int
    title: str
    client_name: str
    additional_context: str | None = None
    generation_mode: GenerationMode | None = None
    page_count: int | None = None
    status: ProposalStatus
    markdown_path: str | None = None
    error_message: str | None = None
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
    content: str | None = None
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


class ExportTemplateResponse(BaseModel):
    id: int
    name: str
    description: str
    preview_url: str | None = None


class ProposalDetailsStep(BaseModel):
    proposal_name: str
    client_name: str
    additional_context: str | None = None
    files: list[RequirementDocumentResponse] = []


class FileSummary(BaseModel):
    """Per-file view of what the parsing pipeline produced. A proposal can
    have several requirement documents, each with its own summary/matches/
    tags, so the wizard can show them side by side."""

    document_id: int
    file_name: str
    status: DocumentStatus
    summary: str | None = None
    knowledge_matches: list[KnowledgeMatch] = []
    capability_tags: list[CapabilityTagOut] = []


class SummaryStep(BaseModel):
    # Aggregated across every uploaded file. `summary` concatenates each
    # file's summary under a "### {file_name}" heading when there is more
    # than one; matches and tags are merged and de-duplicated, keeping the
    # strongest score per knowledge document / capability.
    summary: str | None = None
    knowledge_matches: list[KnowledgeMatch] = []
    capability_tags: list[CapabilityTagOut] = []
    files: list[FileSummary] = []


class GenerationConfigStep(BaseModel):
    generation_mode: GenerationMode | None = None
    page_count: int | None = None


class GenerationStep(BaseModel):
    status: Literal["generating", "done", "failed"]


class ProposalStateResponse(BaseModel):
    proposal_id: int
    current_step: str
    proposal_details: ProposalDetailsStep | None = None
    summary: SummaryStep | None = None
    generation_config: GenerationConfigStep | None = None
    generation: GenerationStep | None = None
