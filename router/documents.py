from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    create_knowledge_document,
    delete_knowledge_document,
    get_knowledge_document_by_id,
    get_knowledge_documents,
    update_knowledge_document,
)
from database.database import get_db
from database.db_enum import IngestionStatus
from database.models import Category, KnowledgeDocument
from schemas.document import DocumentResponse, DocumentUpdateRequest
from tasks.arq_pool import get_arq_pool
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/document",
    tags=["Documents"],
)


def _to_response(document: KnowledgeDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        title=document.title,
        file_name=document.file_name,
        extension=document.extension,
        category_id=document.category_id,
        category_name=document.category.name,
        user_id=document.user_id,
        version=document.version,
        status=document.status,
        created_at=document.created_at,
    )


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: str = Form(...),
    category_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]
    logger.info(
        "upload started | user_id=%s category_id=%s filename=%s",
        user_id, category_id, file.filename,
    )

    category_result = await db.execute(
        select(Category).filter(Category.id == category_id, Category.is_active.is_(True))
    )
    category = category_result.scalars().first()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    extension = Path(file.filename or "").suffix.lstrip(".").lower()

    # Upload to S3 first — no DB record is created unless this succeeds.
    s3_key = S3PathBuilder.knowledge_document(
        user_id=user_id,
        category_id=category_id,
        filename=file.filename,
    )
    try:
        s3_service.upload_file(file, s3_key)
    except Exception:
        logger.exception("upload to S3 failed | user_id=%s filename=%s", user_id, file.filename)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload file to storage. Please try again.",
        )
    logger.info("upload completed | user_id=%s key=%s", user_id, s3_key)

    document = KnowledgeDocument(
        title=title,
        file_name=file.filename,
        file_path=s3_key,
        extension=extension,
        category_id=category_id,
        user_id=user_id,
    )
    document = await create_knowledge_document(db, document)
    logger.info("database entry created | document_id=%s", document.id)

    pool = await get_arq_pool()
    await pool.enqueue_job("knowledge_document_job", document.id)

    return _to_response(document)


@router.post("/{document_id}/process", response_model=DocumentResponse)
async def process_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    pool = await get_arq_pool()
    await pool.enqueue_job("knowledge_document_job", document_id)

    document = await update_knowledge_document(db, document, status=IngestionStatus.PENDING)
    return _to_response(document)


@router.get("/list", response_model=list[DocumentResponse])
async def list_documents(
    category_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    documents = await get_knowledge_documents(db, category_id=category_id)
    return [_to_response(document) for document in documents]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return _to_response(document)


@router.get("/{document_id}/download")
async def download_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    url = s3_service.generate_presigned_url(document.file_path)
    return RedirectResponse(url=url)


@router.put("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: int,
    request: DocumentUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if request.category_id is not None:
        category_result = await db.execute(
            select(Category).filter(
                Category.id == request.category_id, Category.is_active.is_(True)
            )
        )
        category = category_result.scalars().first()
        if category is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    updates = {k: v for k, v in request.model_dump(exclude_unset=True).items() if v is not None}
    document = await update_knowledge_document(db, document, **updates)
    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    await delete_knowledge_document(db, document)
    s3_service.delete_file(document.file_path)
