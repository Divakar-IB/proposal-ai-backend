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
    FileSummary,
    GenerationConfigStep,
    GenerationStep,
    ProposalDetailsStep,
    ProposalGenerateRequest,
    ProposalResponse,
    ProposalSectionMinimal,
    ProposalSectionResponse,
    ProposalSectionsReorderRequest,
    ProposalStateResponse,
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
    done both read as "done" here — status tracking/export are separate
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



def _combined_summary(documents: list) -> str:
    """One summary covering every parsed file. A single file keeps its
    summary verbatim (no heading added, so the single-upload flow renders
    exactly as before); several are concatenated under per-file headings."""

    if len(documents) == 1:
        return documents[0].summary
    return "\n\n".join(f"### {document.file_name}\n\n{document.summary}" for document in documents)


def _merge_knowledge_matches(documents: list) -> list[dict]:
    """Union of every file's knowledge matches, keeping the highest
    match_percent per knowledge document so the same source isn't listed
    once per uploaded file, and ordered strongest-first."""

    best: dict[int, dict] = {}
    for document in documents:
        for match in document.knowledge_matches or []:
            document_id = match.get("document_id")
            current = best.get(document_id)
            if current is None or match.get("match_percent", 0) > current.get("match_percent", 0):
                best[document_id] = match
    return sorted(best.values(), key=lambda match: match.get("match_percent", 0), reverse=True)


def _merge_capability_tags(documents: list) -> list[dict]:
    """Union of every file's capability tags, keeping the highest confidence
    per tag name, ordered most-confident-first."""

    best: dict[str, dict] = {}
    for document in documents:
        for tag in document.capability_tags or []:
            name = tag.get("name")
            current = best.get(name)
            if current is None or tag.get("confidence", 0) > current.get("confidence", 0):
                best[name] = tag
    return sorted(best.values(), key=lambda tag: tag.get("confidence", 0), reverse=True)


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

    file_responses = [_requirement_document_response(document, proposal) for document in documents]
    proposal_details = ProposalDetailsStep(
        proposal_name=proposal.title,
        client_name=proposal.client_name,
        additional_context=proposal.additional_context,
        files=file_responses,
    )

    # Aggregated across every uploaded file, not just the most recent one. A
    # proposal can now carry several requirement documents (see POST
    # /proposals/requirement-documents), and reading only the latest hid the
    # summary, matches and tags of every earlier upload. The per-file
    # breakdown is still available on proposal_details.files.
    summary = None
    parsed_documents = [document for document in documents if document.summary]
    if parsed_documents:
        summary = SummaryStep(
            summary=_combined_summary(parsed_documents),
            knowledge_matches=_merge_knowledge_matches(documents),
            capability_tags=_merge_capability_tags(documents),
            files=[
                FileSummary(
                    document_id=document.id,
                    file_name=document.file_name,
                    status=document.status,
                    summary=document.summary,
                    knowledge_matches=document.knowledge_matches or [],
                    capability_tags=document.capability_tags or [],
                )
                for document in documents
            ],
        )

    generation_config = None
    generation = None
    if proposal.generation_mode is not None:
        generation_config = GenerationConfigStep(
            generation_mode=proposal.generation_mode,
            page_count=proposal.page_count,
        )
        generation = GenerationStep(status=_wizard_generation_status(proposal.status))

    if not documents:
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

