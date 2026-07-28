from datetime import datetime
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
)
from database.database import get_db
from database.db_enum import DocumentStatus, ProposalStatus
from database.models import Proposal, ProposalSection, RequirementDocument
from generation.proposal_generator import generate_proposal_stream
from schemas.proposal import (
    ProposalExportEmailRequest,
    ProposalExportEmailResponse,
    ProposalExportRequest,
    ExportTemplateResponse,
    ProposalDetailResponse,
    ProposalExportResponse,
    ProposalGenerateRequest,
    ProposalListResponse,
    ProposalResponse,
    ProposalSectionMinimal,
    ProposalSectionResponse,
    SectionsBulkEditRequest,
)
from schemas.requirement_document import RequirementDocumentResponse
from services import proposal_export_service, proposal_review_service
from tasks.requirement_processing import process_requirement_document_pipeline
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/proposals",
    tags=["Proposals"],
)


# ------------------------------------------------------------------
# Response builders
# ------------------------------------------------------------------

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


async def _get_proposal_or_404(db: AsyncSession, proposal_id: int) -> Proposal:
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal


# ------------------------------------------------------------------
# Requirement document (upload -> extract/summarize/match, all returned
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
    /generate call will draft into. Must succeed even when there are no
    knowledge documents in the system yet."""

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

    proposal = Proposal(
        user_id=user_id,
        title=proposal_name,
        client_name=client_name,
        additional_context=additional_context,
        status=ProposalStatus.INPROGRESS,
    )
    proposal = await create_proposal(db, proposal)
    logger.info("proposal created | proposal_id=%s", proposal.id)

    document = RequirementDocument(
        file_name=file.filename,
        file_path=s3_key,
        extension=extension,
        user_id=user_id,
        proposal_id=proposal.id,
    )
    document = await create_requirement_document(db, document)
    logger.info("requirement document created | document_id=%s proposal_id=%s", document.id, proposal.id)

    document = await process_requirement_document_pipeline(db, document, additional_context=additional_context)
    if document.status == DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to process requirement document — see server logs for details.",
        )

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
    """Streams the proposal section-by-section as Server-Sent Events —
    section_start -> section_chunk (repeated) -> section_done per section,
    then a final done event. Each section is persisted to the database as
    soon as its draft completes — see generation/proposal_generator.py."""

    proposal = await _get_proposal_or_404(db, request.proposal_id)

    logger.info(
        "proposal generation started | proposal_id=%s mode=%s page_count=%s",
        proposal.id, request.generation_mode, request.page_count,
    )

    return StreamingResponse(
        generate_proposal_stream(
            proposal_id=request.proposal_id,
            page_count=request.page_count,
            generation_mode=request.generation_mode,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/templates", response_model=list[ExportTemplateResponse])
async def list_export_templates(current_user: dict = Depends(get_current_user)):
    """Hardcoded list of available DOCX/PDF export styles — see
    constants.EXPORT_TEMPLATES. Declared before /{proposal_id} so "export-
    templates" isn't swallowed by that dynamic path. preview_url is a
    presigned S3 URL generated fresh on every call (not stored) so it never
    goes stale."""

    return [
        ExportTemplateResponse(
            id=template["id"],
            name=template["name"],
            description=template["description"],
            preview_url=s3_service.generate_presigned_url(template["preview_key"]),
        )
        for template in EXPORT_TEMPLATES
    ]


@router.get("", response_model=ProposalListResponse)
async def list_proposals(
    search: Optional[str] = None,
    status: Optional[ProposalStatus] = None,
    created_by: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Lists proposals for the dashboard — search over title/client_name,
    optional status/created_by/created-date filters, paginated, newest
    first. Reuses the same query-builder + paginate() pattern as
    GET /document/list (see database.crud.build_proposals_query and
    services.proposal_review_service.list_proposals)."""

    result = await proposal_review_service.list_proposals(
        db,
        search=search,
        proposal_status=status,
        created_by=created_by,
        created_from=created_from,
        created_to=created_to,
        page=page,
        limit=limit,
    )
    result["data"] = [_proposal_response(proposal) for proposal in result["data"]]
    return result


# @router.get("/{proposal_id}", response_model=ProposalDetailResponse)
# async def get_proposal(
#     proposal_id: int,
#     db: AsyncSession = Depends(get_db),
#     current_user: dict = Depends(get_current_user),
# ):
#     """Fetches the full proposal for viewing/review — trimmed to just what
#     the reviewer UI needs: proposal identity/status plus each section's id
#     and content, in order."""

#     proposal = await _get_proposal_or_404(db, proposal_id)
#     return _proposal_detail_response(proposal)


# ------------------------------------------------------------------
# Section editing / regeneration
# ------------------------------------------------------------------

@router.patch("/{proposal_id}/sections", response_model=list[ProposalSectionResponse])
async def edit_proposal_sections(
    proposal_id: int,
    request: SectionsBulkEditRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manual edit of one or more sections' content in a single request —
    leaves status/review_flag as-is; approving is a separate explicit
    action below."""

    sections = await proposal_review_service.edit_sections(db, proposal_id, request.sections)
    return [_proposal_section_response(section) for section in sections]


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


# ------------------------------------------------------------------
# Proposal status tracking + export
# ------------------------------------------------------------------

@router.patch("/{proposal_id}/status", response_model=ProposalResponse)
async def set_proposal_status(
    proposal_id: int,
    status: ProposalStatus,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manually moves the proposal-tracking status forward — mainly used to
    mark a proposal DONE once review is finished. Cannot move status
    backward (e.g. generating -> inprogress)."""

    proposal = await proposal_review_service.set_proposal_status(db, proposal_id, status)
    return _proposal_response(proposal)


@router.post("/{proposal_id}/export")
async def export_proposal(
    proposal_id: int,
    request: ProposalExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Renders the proposal's current sections (Markdown -> JSON -> HTML via
    the selected template -> PDF/DOCX) straight from the live section rows —
    not yet gated on approval, since that review/approve flow isn't wired up
    end-to-end yet. Always returns the rendered file as a raw binary response
    (forced download). Emailing the export is a separate endpoint — see
    POST /{proposal_id}/export/email."""

    proposal, content, filename, content_type = await proposal_export_service.render_proposal_document(
        db, proposal_id, request.template_id, request.format
    )

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=content_type, headers=headers)


@router.post("/{proposal_id}/export/email", response_model=ProposalExportEmailResponse)
async def email_proposal_export(
    proposal_id: int,
    request: ProposalExportEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Renders the same way as POST /{proposal_id}/export, but instead of
    returning the file, emails it to the given address and confirms what was
    sent where — no binary is returned to the caller."""

    proposal, content, filename, content_type = await proposal_export_service.render_proposal_document(
        db, proposal_id, request.template_id, request.format
    )

    await proposal_export_service.email_rendered_proposal(
        request.email, proposal, content, filename, content_type
    )

    return ProposalExportEmailResponse(
        proposal_id=proposal.id,
        template_id=request.template_id,
        format=request.format,
        sent_to=request.email,
    )


