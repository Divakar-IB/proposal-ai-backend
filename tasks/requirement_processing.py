from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    get_active_categories,
    get_requirement_document_by_id,
    has_any_knowledge_chunks,
    update_requirement_document,
)
from database.database import db_session
from database.db_enum import DocumentStatus
from database.models import RequirementDocument
from embedding.embedder import embed_query
from extraction.factory import run_extraction
from requirements_parsing.parser import parse_requirements
from requirements_parsing.summary import summarize_requirements
from utilities.logger import get_logger
from utilities.s3_service import S3Service
from vectorstore.knowledge_store import category_match_score

logger = get_logger(__name__)
s3_service = S3Service()

TOP_CATEGORY_MATCHES = 5


async def process_requirement_document_pipeline(
    db: AsyncSession, document: RequirementDocument
) -> RequirementDocument:
    """
    extract -> structured parse (GPT-OSS via Groq) -> summary -> per-category
    knowledge-match scoring -> Postgres storage. Deliberately does NOT touch
    Pinecone with the requirement document's own content — structured output
    becomes the query input for retrieval, it is never embedded itself; the
    only embedding call here is for scoring matches against existing chunks.

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

        requirements = parse_requirements(extracted.markdown)
        logger.info("structured parse completed | document_id=%s", document_id)

        summary = summarize_requirements(extracted.markdown)
        logger.info("summary generated | document_id=%s", document_id)

        knowledge_matches = await _compute_knowledge_matches(db, requirements)
        logger.info("knowledge match scored | document_id=%s categories=%s", document_id, len(knowledge_matches))

        document = await update_requirement_document(
            db, document,
            extracted_markdown=extracted.markdown,
            parsed_data=requirements.model_dump(),
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


async def _compute_knowledge_matches(db: AsyncSession, requirements) -> list[dict]:
    # No knowledge documents indexed yet — skip the embedding call and Pinecone
    # query entirely rather than hitting an empty (or not-yet-created) index.
    if not await has_any_knowledge_chunks(db):
        return []

    query_text = " ".join([
        requirements.project_title,
        requirements.scope,
        " ".join(requirements.technical_requirements),
    ]).strip()
    if not query_text:
        return []

    query_embedding = embed_query(query_text)
    categories = await get_active_categories(db)

    matches = [
        {"category_id": category.id, "category_name": category.name, "match_percent": round(score * 100)}
        for category in categories
        for score in [category_match_score(query_embedding, category.id)]
        if score > 0
    ]
    matches.sort(key=lambda m: m["match_percent"], reverse=True)
    return matches[:TOP_CATEGORY_MATCHES]


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
