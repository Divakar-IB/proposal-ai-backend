from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from constants import EXPORT_TEMPLATES
from database.crud import (
    create_proposal,
    create_requirement_document,
    get_proposal_by_id,
    get_requirement_documents_by_proposal_id,
)
from database.database import get_db
from database.db_enum import DocumentStatus, ProposalStatus
from database.models import Proposal, ProposalSection, RequirementDocument
from generation.proposal_generator import generate_proposal_stream
from schemas.proposal import (
    ProposalExportRequest,
    ExportTemplateResponse,
    ProposalDetailResponse,
    ProposalExportResponse,
    GenerationConfigStep,
    GenerationStep,
    ProposalDetailsStep,
    ProposalGenerateRequest,
    ProposalResponse,
    ProposalSectionMinimal,
    ProposalSectionResponse,
    ProposalSectionsReorderRequest,
    ProposalStateResponse,
    SectionsBulkEditRequest,
    SummaryStep,
)
from schemas.requirement_document import RequirementDocumentResponse
from services import proposal_export_service, proposal_review_service
from tasks.requirement_processing import process_requirement_document_pipeline
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()


router = APIRouter(
    tags=["Proposals"],
)

def _requirement_document_response(
    document: RequirementDocument, proposal: Proposal
) -> RequirementDocumentResponse:
    return RequirementDocumentResponse(
        id=document.id,
        proposal_id=document.proposal_id,
        file_name=document.file_name,
        extension=document.extension,
        user_id=document.user_id,
        proposal_name=proposal.title,
        client_name=proposal.client_name,
        additional_context=proposal.additional_context,
        status=document.status,
        summary=document.summary,
        knowledge_matches=document.knowledge_matches or [],
        capability_tags=document.capability_tags or [],
        created_at=document.created_at,
    )


def _proposal_section_response(section: ProposalSection) -> ProposalSectionResponse:
    return ProposalSectionResponse(
        id=section.id,
        section_key=section.section_key,
        title=section.title,
        order_index=section.order_index,
        content=section.content,
        sources=section.citations,
        status=section.status,
        confidence_score=section.confidence_score,
        review_flag=section.review_flag,
    )


def _proposal_response(proposal: Proposal) -> ProposalResponse:
    return ProposalResponse(
        id=proposal.id,
        requirement_document_ids=[document.id for document in proposal.requirement_documents],
        user_id=proposal.user_id,
        title=proposal.title,
        client_name=proposal.client_name,
        additional_context=proposal.additional_context,
        generation_mode=proposal.generation_mode,
        page_count=proposal.page_count,
        status=proposal.status,
        markdown_path=proposal.markdown_path,
        is_approved=proposal.is_approved,
        approved_markdown=proposal.approved_markdown,
        proposal_json=proposal.proposal_json,
        docx_path=proposal.docx_path,
        pdf_path=proposal.pdf_path,
        error_message=proposal.error_message,
        sections=[_proposal_section_response(section) for section in proposal.sections],
        created_at=proposal.created_at,
    )


def _proposal_detail_response(proposal: Proposal) -> ProposalDetailResponse:
    return ProposalDetailResponse(
        id=proposal.id,
        title=proposal.title,
        client_name=proposal.client_name,
        status=proposal.status,
        sections=[
            ProposalSectionMinimal(
                id=section.id,
                title=section.title,
                content=section.content,
                order=section.order_index,
            )
            for section in proposal.sections
        ],
    )


def _wizard_generation_status(proposal_status: ProposalStatus) -> str:
    """Collapses the full proposal lifecycle down to what the generation
    wizard step cares about: still running, errored, or finished (review/
    approved/done all read as "done" here — approval/export are separate
    steps outside this demo flow)."""

    if proposal_status == ProposalStatus.GENERATING:
        return "generating"
    if proposal_status == ProposalStatus.FAILED:
        return "failed"
    return "done"


async def _get_proposal_or_404(db: AsyncSession, proposal_id: int) -> Proposal:
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal



@router.get("/proposal-state", response_model=ProposalStateResponse)
async def get_proposal_state(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Temporary demo-only endpoint: returns each wizard step's data keyed by
    step name (proposal_details, summary, generation_config, generation), so
    the frontend can resume a proposal wherever the user left off instead of
    restarting the flow. Steps not yet reached come back as null."""

    proposal = await _get_proposal_or_404(db, proposal_id)
    documents = await get_requirement_documents_by_proposal_id(db, proposal_id)
    latest_document = documents[-1] if documents else None

    proposal_details = ProposalDetailsStep(
        proposal_name=proposal.title,
        client_name=proposal.client_name,
        additional_context=proposal.additional_context,
        files=[_requirement_document_response(document, proposal) for document in documents],
    )

    summary = None
    if latest_document is not None and latest_document.summary:
        summary = SummaryStep(
            summary=latest_document.summary,
            knowledge_matches=latest_document.knowledge_matches or [],
            capability_tags=latest_document.capability_tags or [],
        )

    generation_config = None
    generation = None
    if proposal.generation_mode is not None:
        generation_config = GenerationConfigStep(
            generation_mode=proposal.generation_mode,
            page_count=proposal.page_count,
        )
        generation = GenerationStep(status=_wizard_generation_status(proposal.status))

    if latest_document is None:
        current_step = "proposal_details"
    elif summary is None:
        current_step = "summary"
    elif generation_config is None:
        current_step = "generation_config"
    else:
        current_step = "generation"

    return ProposalStateResponse(
        proposal_id=proposal.id,
        current_step=current_step,
        proposal_details=proposal_details,
        summary=summary,
        generation_config=generation_config,
        generation=generation,
    )


@router.get("/proposal-sections", response_model=ProposalDetailResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Fetches the full proposal for viewing/review — trimmed to just what
    the reviewer UI needs: proposal identity/status plus each section's id
    and content, in order."""

    proposal = await _get_proposal_or_404(db, proposal_id)
    return _proposal_detail_response(proposal)


@router.patch("/proposal-sections", response_model=ProposalDetailResponse)
async def edit_proposal_sections(
    proposal_id: int,
    payload: ProposalSectionsReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Temporary demo-only endpoint: reorders/removes sections without
    regenerating content. Sections omitted from the payload are deleted;
    sections included have their order_index set to the given order."""

    proposal = await _get_proposal_or_404(db, proposal_id)

    existing_by_id = {section.id: section for section in proposal.sections}

    for item in payload.sections:
        if item.id not in existing_by_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Section {item.id} does not belong to proposal {proposal_id}",
            )

    keep_ids = {item.id for item in payload.sections}
    for section_id, section in existing_by_id.items():
        if section_id not in keep_ids:
            await db.delete(section)

    for item in payload.sections:
        existing_by_id[item.id].order_index = item.order

    await db.commit()
    await db.refresh(proposal)
    return _proposal_detail_response(proposal)

