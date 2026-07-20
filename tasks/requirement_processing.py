from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    get_knowledge_documents_by_ids,
    get_requirement_document_by_id,
    has_any_knowledge_chunks,
    update_requirement_document,
)
from database.database import db_session
from database.db_enum import DocumentStatus
from database.models import RequirementDocument
from embedding.embedder import embed_query
from extraction.factory import run_extraction
from requirements_parsing.summary import summarize_requirements
from utilities.logger import get_logger
from utilities.s3_service import S3Service
from vectorstore.knowledge_store import query_chunks

logger = get_logger(__name__)
s3_service = S3Service()

TOP_DOCUMENT_MATCHES = 10
CHUNK_POOL_SIZE = 30  # pulled before deduping to one best match per document


async def process_requirement_document_pipeline(
    db: AsyncSession, document: RequirementDocument, additional_context: Optional[str] = None
) -> RequirementDocument:
    """
    extract -> summary (GPT-OSS via Groq) -> per-document knowledge-match
    scoring (using the summary as the query text) -> Postgres storage.

    Shared core used both by the upload endpoint (awaited synchronously, so
    the caller gets the summary/matches back in the same response) and by
    the standalone background entry point below.
    """
    document_id = document.id
    await update_requirement_document(db, document, status=DocumentStatus.EXTRACTING)
    temp_path: Optional[str] = None

    try:
        temp_path = s3_service.download_to_tempfile(document.file_path, suffix=f".{document.extension}")
        logger.info("file fetched from S3 | document_id=%s key=%s", document_id, document.file_path)

        extracted = run_extraction(temp_path, document.file_name, document.extension)
        logger.info(
            "extraction completed | document_id=%s chars=%s pages=%s",
            document_id, len(extracted.markdown), len(extracted.pages),
        )

        summary = summarize_requirements(extracted.markdown, additional_context=additional_context)
        logger.info("summary generated | document_id=%s", document_id)

        knowledge_matches = await _compute_knowledge_matches(db, summary)
        logger.info("knowledge match scored | document_id=%s matches=%s", document_id, len(knowledge_matches))

        document = await update_requirement_document(
            db, document,
            extracted_markdown=extracted.markdown,
            summary=summary,
            knowledge_matches=knowledge_matches,
            status=DocumentStatus.PARSED,
        )
        logger.info("processing completed | document_id=%s", document_id)
        return document

    except Exception:
        logger.exception("processing failed | document_id=%s", document_id)
        return await update_requirement_document(db, document, status=DocumentStatus.FAILED)

    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
            logger.info("temp file cleaned up | document_id=%s path=%s", document_id, temp_path)


async def _compute_knowledge_matches(db: AsyncSession, query_text: str) -> list[dict]:
    # No knowledge documents indexed yet — skip the embedding call and Pinecone
    # query entirely rather than hitting an empty (or not-yet-created) index.
    if not await has_any_knowledge_chunks(db):
        return []

    if not query_text.strip():
        return []

    query_embedding = embed_query(query_text)
    chunks = query_chunks(query_embedding, top_k=CHUNK_POOL_SIZE)

    # Keep each document's single highest-scoring chunk — chunks come back
    # sorted by score descending, so the first hit per document_id is its best.
    best_chunk_by_document: dict[int, dict] = {}
    for chunk in chunks:
        document_id = chunk["document_id"]
        if document_id not in best_chunk_by_document:
            best_chunk_by_document[document_id] = chunk

    documents = await get_knowledge_documents_by_ids(db, list(best_chunk_by_document.keys()))
    title_by_document_id = {document.id: document.title for document in documents}

    matches = [
        {
            "document_id": document_id,
            "title": title_by_document_id.get(document_id, chunk["source_filename"]),
            "source_filename": chunk["source_filename"],
            "breadcrumb": chunk["breadcrumb"],
            "match_percent": round(chunk["score"] * 100),
        }
        for document_id, chunk in best_chunk_by_document.items()
    ]
    matches.sort(key=lambda m: m["match_percent"], reverse=True)
    return matches[:TOP_DOCUMENT_MATCHES]


async def process_requirement_document(document_id: int) -> None:
    """Standalone background entry point (e.g. an Arq job) — opens its own
    session. Not currently used by the upload endpoint, which awaits
    process_requirement_document_pipeline directly instead so the summary
    and knowledge matches can be returned in the same HTTP response."""

    logger.info("background task started | document_id=%s", document_id)
    async with db_session() as db:
        document = await get_requirement_document_by_id(db, document_id)
        if document is None:
            logger.error("document not found, aborting | document_id=%s", document_id)
            return
        await process_requirement_document_pipeline(db, document)
