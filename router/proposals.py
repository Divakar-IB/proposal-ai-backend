from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from constants import EXPORT_TEMPLATES
from database.crud import (
    create_proposal,
    create_requirement_document,
    delete_proposal,
    get_organization_settings,
    get_proposal_by_id,
    update_proposal,
)
from database.database import get_db
from database.db_enum import DocumentStatus, ProposalStatus
from database.models import Proposal, ProposalSection, RequirementDocument
from generation.proposal_generator import generate_proposal_stream
from services.proposal_knowledge_service import ingest_proposal_as_knowledge
from services.proposal_naming_service import generate_proposal_name
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
    ProposalStatsResponse,
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
    document: RequirementDocument,
    proposal: Proposal,
    additional_documents: Optional[list[RequirementDocument]] = None,
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
        additional_documents=[
            _requirement_document_response(extra, proposal)
            for extra in (additional_documents or [])
        ],
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
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
    proposal_id: Optional[int] = Form(None),
    proposal_name: Optional[str] = Form(None),
    client_name: str = Form(...),
    additional_context: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Uploads one or more requirement documents, then fetches each back from
    S3 and runs the pipeline (extract -> summary -> knowledge-base match
    scoring) synchronously per file, in upload order, so the caller gets the
    summary/matches back here directly instead of polling a separate status
    endpoint. Files are processed one at a time (not concurrently) — the
    pipeline shares one request-scoped DB session, which isn't safe for
    concurrent use, and the LLM calls inside it are blocking anyway so
    concurrency would buy nothing.

    `file` (singular) is the original field — still accepted as-is for
    existing callers. `files` (plural) additionally accepts more than one
    upload in the same call; both can be combined. Pass `proposal_id` to
    attach new documents to an already-created proposal instead of starting
    a new one (proposal_name/client_name/additional_context are then only
    used as extraction context for the new files, not applied to the
    existing proposal). Omitting `proposal_name` on a new proposal defers
    naming until the first file's requirements are parsed — see
    services.proposal_naming_service."""

    user_id = current_user["user_id"]

    uploads: list[UploadFile] = list(files) if files else []
    if file is not None:
        uploads.insert(0, file)
    if not uploads:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one file is required (file or files).",
        )

    if proposal_id is not None:
        proposal = await _get_proposal_or_404(db, proposal_id)
    else:
        proposal = Proposal(
            user_id=user_id,
            title=proposal_name or client_name,
            client_name=client_name,
            additional_context=additional_context,
            status=ProposalStatus.INPROGRESS,
        )
        proposal = await create_proposal(db, proposal)
        logger.info("proposal created | proposal_id=%s", proposal.id)

    documents: list[RequirementDocument] = []
    for upload in uploads:
        extension = Path(upload.filename or "").suffix.lstrip(".").lower()

        s3_key = S3PathBuilder.requirement_document(user_id=user_id, filename=upload.filename)
        try:
            s3_service.upload_file(upload, s3_key)
        except Exception:
            logger.exception("upload to S3 failed | user_id=%s filename=%s", user_id, upload.filename)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to upload file to storage. Please try again.",
            )

        document = RequirementDocument(
            file_name=upload.filename,
            file_path=s3_key,
            extension=extension,
            user_id=user_id,
            proposal_id=proposal.id,
        )
        document = await create_requirement_document(db, document)
        logger.info(
            "requirement document created | document_id=%s proposal_id=%s", document.id, proposal.id
        )

        document = await process_requirement_document_pipeline(
            db, document, additional_context=additional_context
        )
        documents.append(document)

    primary_document = documents[0]
    if primary_document.status == DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to process requirement document — see server logs for details.",
        )

    # Auto-name a brand-new proposal from the first successfully-parsed
    # document's project_title, unless the caller already gave it an
    # explicit name.
    if proposal_id is None and proposal_name is None and primary_document.parsed_data:
        project_title = primary_document.parsed_data.get("project_title")
        if project_title:
            org_settings = await get_organization_settings(db)
            generated_name = generate_proposal_name(
                client_name=client_name,
                project_title=project_title,
                organization_name=org_settings.organization_name if org_settings else None,
                template=org_settings.proposal_naming_template if org_settings else None,
            )
            proposal = await update_proposal(db, proposal, title=generated_name)
            logger.info("proposal auto-named | proposal_id=%s title=%s", proposal.id, generated_name)

    return _requirement_document_response(primary_document, proposal, documents[1:])


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


@router.get("/stats", response_model=ProposalStatsResponse)
async def get_proposal_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Overall proposal count plus a per-status breakdown, for dashboard
    tiles. Declared before /{proposal_id}/... paths so "stats" isn't
    swallowed by a dynamic path."""

    return await proposal_review_service.get_proposal_stats(db)


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


@router.delete("/{proposal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proposal_endpoint(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Soft-deletes the proposal (is_active=False), the same pattern already
    used for Proposal elsewhere in this module (get_proposal_by_id and
    build_proposals_query both filter on is_active) — so it drops out of
    GET /proposals immediately. Sections and requirement documents are left
    as-is, matching how deleting a knowledge document doesn't cascade to its
    chunks either."""

    proposal = await _get_proposal_or_404(db, proposal_id)
    await delete_proposal(db, proposal)


# ------------------------------------------------------------------
# Proposal status tracking + export
# ------------------------------------------------------------------

@router.patch("/{proposal_id}/status", response_model=ProposalResponse)
async def set_proposal_status(
    proposal_id: int,
    status: ProposalStatus,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manually moves the proposal-tracking status forward — mainly used to
    mark a proposal DONE once review is finished. Cannot move status
    backward (e.g. generating -> inprogress).

    This is the deliberate "approve" action (as opposed to export's own,
    unrelated auto-DONE side effect — see proposal_export_service): every
    time it's called with status=done, it schedules a background re-
    ingestion of the proposal's current content into the knowledge base
    (see services.proposal_knowledge_service), not just on the first
    transition. Calling this repeatedly after further edits re-indexes the
    latest content each time."""

    proposal = await proposal_review_service.set_proposal_status(db, proposal_id, status)

    if status == ProposalStatus.DONE:
        background_tasks.add_task(ingest_proposal_as_knowledge, proposal.id)

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


