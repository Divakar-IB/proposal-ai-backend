from pathlib import Path
from typing import Optional

from chunking.models import Chunk
from chunking.pipeline import chunk_document
from config import config
from database.crud import (
    create_knowledge_chunks,
    delete_knowledge_chunks_for_document,
    get_knowledge_document_by_id,
    get_organization_settings,
    update_knowledge_document,
)
from database.database import db_session
from database.db_enum import IngestionStatus, KnowledgeSourceType
from database.models import KnowledgeChunk
from embedding.embedder import embed_texts
from extraction.base import ExtractedDocument
from extraction.factory import run_extraction
from utilities.logger import get_logger
from utilities.s3_service import S3Service
from vectorstore.knowledge_store import delete_document_vectors, upsert_chunks

logger = get_logger(__name__)
s3_service = S3Service()


def extract_document(file_path: str, source_filename: str, extension: str) -> ExtractedDocument:
    return run_extraction(file_path, source_filename, extension)


def build_chunks(document: ExtractedDocument, root_prefix: str) -> list[Chunk]:
    return chunk_document(document, root_prefix=root_prefix)


def generate_embeddings(chunks: list[Chunk]) -> list[list[float]]:
    return embed_texts([chunk.content for chunk in chunks])


# ------------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------------

async def process_knowledge_document(document_id: int) -> None:
    """
    Runs as a background task (Arq job) after a successful upload.
    Opens its own DB session — the request-scoped session used by the
    upload endpoint is already closed by the time this runs.
    """
    logger.info("background task started | document_id=%s", document_id)
    temp_path: Optional[str] = None

    async with db_session() as db:
        document = await get_knowledge_document_by_id(db, document_id)
        if document is None:
            logger.error("document not found, aborting | document_id=%s", document_id)
            return

        await update_knowledge_document(db, document, status=IngestionStatus.PROCESSING)

        try:
            temp_path = s3_service.download_to_tempfile(
                document.file_path, suffix=f".{document.extension}"
            )
            logger.info(
                "file downloaded from S3 | document_id=%s key=%s",
                document_id, document.file_path,
            )

            logger.info(
                "extraction started | document_id=%s extension=%s",
                document_id, document.extension,
            )
            extracted = extract_document(temp_path, document.file_name, document.extension)
            logger.info(
                "extraction completed | document_id=%s chars=%s pages=%s",
                document_id, len(extracted.markdown), len(extracted.pages),
            )
            await update_knowledge_document(db, document, extracted_markdown=extracted.markdown)

            root_prefix = f"{document.category.name} > {document.title}"
            chunks = build_chunks(extracted, root_prefix)
            logger.info("chunking completed | document_id=%s chunks=%s", document_id, len(chunks))

            embeddings = generate_embeddings(chunks)
            logger.info("embeddings generated | document_id=%s count=%s", document_id, len(embeddings))
            embedding_version = config.hf_inference.embedding_model

            # Re-processing (new version) wipes prior vectors/rows first — avoids orphaned
            # Pinecone vectors and duplicate KnowledgeChunk rows for the same document.
            delete_document_vectors(document_id)
            await delete_knowledge_chunks_for_document(db, document_id)

            organization_name = None
            if document.source_type == KnowledgeSourceType.PROPOSAL:
                org_settings = await get_organization_settings(db)
                organization_name = org_settings.organization_name if org_settings else None

            vector_ids = upsert_chunks(
                document_id=document_id,
                category_id=document.category_id,
                source_filename=document.file_name,
                chunks=chunks,
                embeddings=embeddings,
                source_type=document.source_type.value,
                source_proposal_id=document.source_proposal_id,
                organization_name=organization_name,
                embedding_version=embedding_version,
            )
            logger.info("pinecone upload completed | document_id=%s", document_id)

            chunk_rows = [
                KnowledgeChunk(
                    knowledge_document_id=document_id,
                    chunk_index=chunk.chunk_index,
                    breadcrumb=chunk.breadcrumb,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    token_count=chunk.token_count,
                    pinecone_vector_id=vector_id,
                    embedding_version=embedding_version,
                )
                for chunk, vector_id in zip(chunks, vector_ids)
            ]
            await create_knowledge_chunks(db, chunk_rows)
            logger.info("chunk rows persisted | document_id=%s count=%s", document_id, len(chunk_rows))

            await update_knowledge_document(db, document, status=IngestionStatus.INDEXED)
            logger.info("processing completed | document_id=%s", document_id)

        except Exception:
            logger.exception("processing failed | document_id=%s", document_id)
            await update_knowledge_document(db, document, status=IngestionStatus.FAILED)

        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)
                logger.info("temp file cleaned up | document_id=%s path=%s", document_id, temp_path)
