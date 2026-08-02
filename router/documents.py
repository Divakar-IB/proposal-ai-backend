from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    build_knowledge_documents_query,
    create_knowledge_document,
    delete_knowledge_chunks_for_document,
    delete_knowledge_document,
    get_knowledge_document_by_id,
    update_knowledge_document,
)
from database.database import get_db
from database.db_enum import DocumentAvailability, IngestionStatus
from database.models import Category, KnowledgeDocument
from schemas.document import DocumentListResponse, DocumentResponse
from tasks.document_processing import process_knowledge_document
from utilities.pagination import paginate
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service
from vectorstore.knowledge_store import delete_document_vectors

logger = get_logger(__name__)
s3_service = S3Service()

router = APIRouter(
    prefix="/document",
    tags=["Documents"],
)


def _to_response(document: KnowledgeDocument) -> DocumentResponse:
    return DocumentResponse(
        id=document.id,
        document_name=document.title,
        description=document.description,
        file_name=document.file_name,
        extension=document.extension,
        category_id=document.category_id,
        category_name=document.category.name,
        user_id=document.user_id,
        version=document.version,
        status=document.status,
        availability_status=document.availability_status,
        tags=document.tags or [],
        url=s3_service.generate_presigned_url(document.file_path),
        created_at=document.created_at,
    )


async def _resolve_category_or_404(db: AsyncSession, category_id: int) -> Category:
    result = await db.execute(
        select(Category).filter(Category.id == category_id, Category.is_active.is_(True))
    )
    category = result.scalars().first()
    if category is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return category


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
     document_id: Optional[int] = Form(None),
    
    document_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    category_id: Optional[int] = Form(None),
    availability_status: Optional[DocumentAvailability] = Form(None),
    tags: Optional[list[str]] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Creates a new knowledge document, or edits an existing one when the
    `document_id` form field is supplied.

    On edit every field is optional — send only what changed. Omitting `file`
    keeps the current file; sending one replaces it and triggers a
    re-chunk/re-embed in the background. On create, `document_name`,
    `category_id` and `file` are required.
    """

    user_id = current_user["user_id"]

    # A browser that submits a file input with nothing chosen still sends an
    # empty part; treat that as "no file" rather than uploading a 0-byte object
    # under a blank filename.
    if file is not None and not (file.filename or "").strip():
        file = None

    # ------------------------------------------------------------------
    # Edit an existing document
    # ------------------------------------------------------------------
    if document_id is not None:
        document = await get_knowledge_document_by_id(db, document_id)
        if document is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        updates: dict = {}
        if document_name is not None:
            updates["title"] = document_name
        if description is not None:
            updates["description"] = description
        if availability_status is not None:
            updates["availability_status"] = availability_status
        # `[]` is meaningful here (clear all tags); only `None` means untouched.
        if tags is not None:
            updates["tags"] = tags
        if category_id is not None:
            await _resolve_category_or_404(db, category_id)
            updates["category_id"] = category_id

        if file is not None:
            effective_category_id = category_id if category_id is not None else document.category_id
            extension = Path(file.filename or "").suffix.lstrip(".").lower()
            s3_key = S3PathBuilder.knowledge_document(
                user_id=user_id,
                category_id=effective_category_id,
                filename=file.filename,
                document_id=document_id,
            )
            try:
                s3_service.upload_file(file, s3_key)
            except Exception:
                logger.exception(
                    "re-upload to S3 failed | document_id=%s filename=%s",
                    document_id, file.filename,
                )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Failed to upload file to storage. Please try again.",
                )

            old_file_path = document.file_path
            updates.update({
                "file_name": file.filename,
                "file_path": s3_key,
                "extension": extension,
                "version": document.version + 1,
            })
            s3_service.delete_file(old_file_path)
            logger.info("file replaced | document_id=%s key=%s", document_id, s3_key)

        if updates:
            document = await update_knowledge_document(db, document, **updates)
        logger.info(
            "document updated | document_id=%s fields=%s file_replaced=%s",
            document.id, sorted(updates), file is not None,
        )

        if file is not None:
            # File content changed — re-chunk/re-embed/re-upsert in the background.
            background_tasks.add_task(process_knowledge_document, document.id)

        return _to_response(document)

    # ------------------------------------------------------------------
    # Create a new document
    # ------------------------------------------------------------------
    missing = [
        name for name, value in (
            ("document_name", document_name), ("category_id", category_id), ("file", file)
        ) if value is None
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} required when "
                "creating a document. To edit an existing one, pass document_id."
            ),
        )

    await _resolve_category_or_404(db, category_id)

    logger.info(
        "upload started | user_id=%s category_id=%s filename=%s",
        user_id, category_id, file.filename,
    )

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
        title=document_name,
        description=description,
        file_name=file.filename,
        file_path=s3_key,
        extension=extension,
        category_id=category_id,
        user_id=user_id,
        tags=tags or [],
        availability_status=availability_status or DocumentAvailability.ACTIVE,
    )
    document = await create_knowledge_document(db, document)
    logger.info("database entry created | document_id=%s", document.id)

    background_tasks.add_task(process_knowledge_document, document.id)

    return _to_response(document)


@router.get("/list", response_model=DocumentListResponse)
async def list_documents(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    status: Optional[DocumentAvailability] = None,
    include_generated: bool = False,
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """`include_generated=True` also surfaces knowledge documents that were
    auto-ingested from an approved proposal (see PATCH
    /proposals/{id}/status) — hidden by default so the manual-upload list
    doesn't get mixed in with those."""

    query = build_knowledge_documents_query(
        category_id=category_id,
        search=search,
        knowledge_status=status,
        include_generated=include_generated,
    )
    return await paginate(db, query, page=page, limit=limit, serializer=_to_response)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return _to_response(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    document = await get_knowledge_document_by_id(db, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # If this raises an exception, your middleware will return a 500 response.
    s3_service.delete_file(document.file_path)

    # Clean up the indexed side (Pinecone vectors + Postgres chunk rows) before
    # the soft-delete — otherwise they'd stay live forever and, for a
    # proposal-derived document, a later re-ingestion would violate the
    # source_proposal_id uniqueness the upsert relies on.
    delete_document_vectors(document_id)
    await delete_knowledge_chunks_for_document(db, document_id)

    # Only executed if the above succeeded.
    await delete_knowledge_document(db, document)