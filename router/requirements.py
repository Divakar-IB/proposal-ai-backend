from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    create_requirement_document,
    get_requirement_document_by_id,
    update_requirement_document,
)
from database.database import get_db
from database.db_enum import DocumentStatus
from database.models import RequirementDocument
from schemas.requirement_document import RequirementDocumentResponse
from tasks.arq_pool import get_arq_pool
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/requirement-documents",
    tags=["Requirement Documents"],
)


def _to_response(document: RequirementDocument) -> RequirementDocumentResponse:
    return RequirementDocumentResponse(
        id=document.id,
        file_name=document.file_name,
        extension=document.extension,
        user_id=document.user_id,
        status=document.status,
        parsed_data=document.parsed_data,
        created_at=document.created_at,
    )


@router.post("/upload", response_model=RequirementDocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_requirement_document(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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

    pool = await get_arq_pool()
    await pool.enqueue_job("requirement_document_job", document.id)

    return _to_response(document)


@router.post("/{document_id}/process", response_model=RequirementDocumentResponse)
async def process_requirement_document_endpoint(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_requirement_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")

    pool = await get_arq_pool()
    await pool.enqueue_job("requirement_document_job", document_id)

    document = await update_requirement_document(db, document, status=DocumentStatus.EXTRACTING)
    return _to_response(document)


@router.get("/{document_id}", response_model=RequirementDocumentResponse)
async def get_requirement_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_requirement_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")
    return _to_response(document)
