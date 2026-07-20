from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    create_proposal,
    create_requirement_document,
    get_proposal_by_id,
    get_requirement_document_by_id,
)
from database.database import get_db
from database.db_enum import DocumentStatus, ProposalStatus
from database.models import Proposal, RequirementDocument
from generation.graph import stream_proposal_generation
from schemas.proposal import ProposalGenerateRequest, ProposalResponse
from schemas.requirement_document import RequirementDocumentResponse
from tasks.requirement_processing import process_requirement_document_pipeline
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/proposals",
    tags=["Proposals"],
)


def _requirement_document_response(document: RequirementDocument) -> RequirementDocumentResponse:
    return RequirementDocumentResponse(
        id=document.id,
        file_name=document.file_name,
        extension=document.extension,
        user_id=document.user_id,
        status=document.status,
        parsed_data=document.parsed_data,
        summary=document.summary,
        knowledge_matches=document.knowledge_matches or [],
        created_at=document.created_at,
    )


# ------------------------------------------------------------------
# Requirement documents (upload -> extract/parse/summarize/match, all
# returned synchronously in this same response)
# ------------------------------------------------------------------

@router.post(
    "/requirement-documents",
    response_model=RequirementDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_requirement_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Uploads to S3, then fetches it back from S3 and runs the full pipeline
    (extract -> structured parse -> summary -> knowledge-base match scoring)
    synchronously, so the caller gets the summary and matches back here
    directly instead of polling a separate status endpoint."""

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

    document = await process_requirement_document_pipeline(db, document)

    if document.status == DocumentStatus.FAILED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Failed to process requirement document — see server logs for details.",
        )

    return _requirement_document_response(document)


@router.get("/requirement-documents/{document_id}", response_model=RequirementDocumentResponse)
async def get_requirement_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_requirement_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")
    return _requirement_document_response(document)


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

    proposal = Proposal(
        requirement_document_id=request.requirement_document_id,
        user_id=user_id,
        title=f"Proposal — {requirement_document.file_name}",
        status=ProposalStatus.GENERATING,
    )
    proposal = await create_proposal(db, proposal)
    logger.info(
        "proposal created | proposal_id=%s requirement_document_id=%s",
        proposal.id, request.requirement_document_id,
    )

    return StreamingResponse(
        stream_proposal_generation(
            requirement_document_id=request.requirement_document_id,
            proposal_id=proposal.id,
            user_id=user_id,
            category_ids=request.category_ids,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal
