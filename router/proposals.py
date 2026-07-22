from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    build_proposals_query,
    create_proposal,
    create_requirement_document,
    get_categories_by_names,
    get_proposal_by_id,
    get_proposal_by_requirement_document_id,
    get_requirement_document_by_id,
    update_proposal,
)
from database.database import get_db
from database.db_enum import DocumentStatus, ProposalSectionStatus, ProposalStatus
from database.models import Proposal, ProposalSection, RequirementDocument
from generation.graph import stream_proposal_generation
from schemas.proposal import (
    ProposalGenerateRequest,
    ProposalListItem,
    ProposalListResponse,
    ProposalResponse,
    ProposalSectionResponse,
    SectionEditRequest,
)
from schemas.requirement_document import RequirementDocumentResponse
from services import proposal_review_service
from tasks.requirement_processing import process_requirement_document_pipeline
from utilities.logger import get_logger
from utilities.pagination import paginate
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/proposals",
    tags=["Proposals"],
)


def _requirement_document_response(
    document: RequirementDocument, proposal: Proposal
) -> RequirementDocumentResponse:
    return RequirementDocumentResponse(
        id=document.id,
        proposal_id=proposal.id,
        file_name=document.file_name,
        extension=document.extension,
        user_id=document.user_id,
        proposal_name=proposal.title,
        client_name=proposal.client_name,
        additional_context=proposal.additional_context,
        status=document.status,
        summary=document.summary,
        parsed_requirements=document.parsed_data,
        knowledge_matches=document.knowledge_matches or [],
        capability_tags=document.capability_tags or [],
        created_at=document.created_at,
    )


def _proposal_section_response(section: ProposalSection) -> ProposalSectionResponse:
    return ProposalSectionResponse(
        id=section.id,
        section_key=section.section_key,
        order_index=section.order_index,
        content=section.content,
        sources=section.citations,
        status=section.status,
        confidence_score=section.confidence_score,
        review_flag=section.review_flag,
    )


def _proposal_list_item(proposal: Proposal) -> ProposalListItem:
    approved = sum(
        1 for section in proposal.sections if section.status == ProposalSectionStatus.APPROVED
    )
    return ProposalListItem(
        id=proposal.id,
        requirement_document_id=proposal.requirement_document_id,
        user_id=proposal.user_id,
        title=proposal.title,
        client_name=proposal.client_name,
        status=proposal.status,
        total_sections=len(proposal.sections),
        approved_sections=approved,
        created_at=proposal.created_at,
        updated_at=proposal.updated_at,
    )


def _proposal_response(proposal: Proposal) -> ProposalResponse:
    return ProposalResponse(
        id=proposal.id,
        requirement_document_id=proposal.requirement_document_id,
        user_id=proposal.user_id,
        title=proposal.title,
        status=proposal.status,
        markdown_path=proposal.markdown_path,
        docx_path=proposal.docx_path,
        error_message=proposal.error_message,
        sections=[_proposal_section_response(section) for section in proposal.sections],
        created_at=proposal.created_at,
    )


# ------------------------------------------------------------------
# Requirement documents (upload -> extract/summarize/match, all returned
# synchronously in this same response)
# ------------------------------------------------------------------

@router.post(
    "/requirement-documents",
    response_model=RequirementDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_requirement_document(
    file: UploadFile = File(...),
    proposal_name: str = Form(...),
    client_name: str = Form(...),
    additional_context: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Uploads to S3, then fetches it back from S3 and runs the pipeline
    (extract -> summary -> knowledge-base match scoring) synchronously, so
    the caller gets the summary and matches back here directly instead of
    polling a separate status endpoint. Also creates the Proposal row up
    front (title/client_name/additional_context), which the later
    /generate call will draft into."""

    user_id = current_user["user_id"]
    extension = Path(file.filename or "").suffix.lstrip(".").lower()

    s3_key = S3PathBuilder.requirement_document(user_id=user_id, filename=file.filename)
    try:
        s3_service.upload_file(file, s3_key)
    except Exception:
        logger.exception("upload to S3 failed | user_id=%s filename=%s", user_id, file.filename)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload file to storage. Please try again.",
        )

    document = RequirementDocument(
        file_name=file.filename,
        file_path=s3_key,
        extension=extension,
        user_id=user_id,
    )
    document = await create_requirement_document(db, document)
    logger.info("requirement document created | document_id=%s", document.id)

    proposal = Proposal(
        requirement_document_id=document.id,
        user_id=user_id,
        title=proposal_name,
        client_name=client_name,
        additional_context=additional_context,
        status=ProposalStatus.INPROGRESS,
    )
    proposal = await create_proposal(db, proposal)
    logger.info("proposal created | proposal_id=%s document_id=%s", proposal.id, document.id)

    document = await process_requirement_document_pipeline(db, document, additional_context=additional_context)

    if document.status == DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to process requirement document — see server logs for details.",
        )

    return _requirement_document_response(document, proposal)


@router.get("/requirement-documents/{document_id}", response_model=RequirementDocumentResponse)
async def get_requirement_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_requirement_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")

    proposal = await get_proposal_by_requirement_document_id(db, document_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found for this document")

    return _requirement_document_response(document, proposal)


# ------------------------------------------------------------------
# Proposal generation (streaming) + retrieval
# ------------------------------------------------------------------

@router.post("/generate")
async def generate_proposal_endpoint(
    request: ProposalGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Streams proposal generation progress as Server-Sent Events — one
    "section" event each time a section is drafted, sent back for revision,
    or approved, followed by a final "done"/"failed" event. The compiled
    Proposal + ProposalSection rows are persisted by the graph's own
    compile_proposal node once all sections settle."""

    user_id = current_user["user_id"]

    requirement_document = await get_requirement_document_by_id(db, request.requirement_document_id)
    if requirement_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")

    proposal = await get_proposal_by_requirement_document_id(db, request.requirement_document_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No proposal found for this requirement document — upload it via /requirement-documents first.",
        )

    # Pass the hidden step's capability tags directly to generation when the
    # caller doesn't explicitly scope retrieval themselves. Resolved once here
    # (not per-section) and persisted onto the Proposal row so a later
    # "regenerate one section" call can reuse the same knowledge-base scope.
    category_ids = request.category_ids
    if not category_ids and requirement_document.capability_tags:
        tag_names = [tag["name"] for tag in requirement_document.capability_tags]
        categories = await get_categories_by_names(db, tag_names)
        category_ids = [category.id for category in categories] or None

    proposal = await update_proposal(
        db, proposal, status=ProposalStatus.GENERATING, category_ids=category_ids
    )
    logger.info(
        "proposal generation started | proposal_id=%s requirement_document_id=%s category_ids=%s",
        proposal.id, request.requirement_document_id, category_ids,
    )

    return StreamingResponse(
        stream_proposal_generation(
            requirement_document_id=request.requirement_document_id,
            proposal_id=proposal.id,
            user_id=user_id,
            category_ids=category_ids,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/", response_model=ProposalListResponse)
async def list_proposals(
    client_name: Optional[str] = None,
    status: Optional[ProposalStatus] = None,
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    query = build_proposals_query(client_name=client_name, proposal_status=status)
    return await paginate(db, query, page=page, limit=limit, serializer=_proposal_list_item)


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return _proposal_response(proposal)


# ------------------------------------------------------------------
# Review & Refine — per-section edit / regenerate / approve
# ------------------------------------------------------------------

@router.patch("/sections/{section_id}", response_model=ProposalSectionResponse)
async def edit_proposal_section(
    section_id: int,
    request: SectionEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manual edit of a section's content — leaves status/review_flag as-is;
    approving is a separate explicit action below."""

    section = await proposal_review_service.edit_section(db, section_id, request)
    return _proposal_section_response(section)


@router.post("/sections/{section_id}/regenerate", response_model=ProposalSectionResponse)
async def regenerate_proposal_section(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """One fresh draft + quality-check pass for a single section — reuses the
    same knowledge-base scope (Proposal.category_ids) and structured
    requirements the original generation run used."""

    section = await proposal_review_service.regenerate_section(db, section_id)
    return _proposal_section_response(section)


@router.post("/sections/{section_id}/approve", response_model=ProposalSectionResponse)
async def approve_proposal_section(
    section_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    section = await proposal_review_service.approve_section(db, section_id)
    return _proposal_section_response(section)
