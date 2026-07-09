from pathlib import Path
from typing import Optional

from database.crud import get_knowledge_document_by_id, update_knowledge_document
from database.database import db_session
from database.db_enum import IngestionStatus
from extraction.docx_extractor import DocxExtractor
from utilities.logger import get_logger
from utilities.s3_service import S3Service

logger = get_logger(__name__)
s3_service = S3Service()


# ------------------------------------------------------------------
# Extension points — plug your parsing / chunking / embedding /
# Pinecone code in here. Everything else in this file is orchestration
# (download, status updates, logging, error handling, cleanup) and
# shouldn't need to change as you fill these in.
# ------------------------------------------------------------------

def extract_text(file_path: str, extension: str) -> str:
    if extension == "docx":
        extracted = DocxExtractor().extract(file_path)
        return DocxExtractor().to_json(extracted)
    if extension == "pdf":
        raise NotImplementedError("TODO: implement PDF parsing")
    if extension in {"png", "jpg", "jpeg"}:
        raise NotImplementedError("TODO: implement image OCR parsing")
    raise NotImplementedError(f"No parser registered for '.{extension}'")


def chunk_text(text: str) -> list[str]:
    raise NotImplementedError("TODO: implement chunking (RAG/chunking.py)")


def generate_embeddings(chunks: list[str]) -> list[list[float]]:
    raise NotImplementedError("TODO: implement embeddings (vectorstore/embedding.py)")


def upsert_vectors(document_id: int, chunks: list[str], embeddings: list[list[float]]) -> None:
    raise NotImplementedError(
        "TODO: implement Pinecone upsert (vectorstore/pinecone_client.py + index_manager.py)"
    )


# ------------------------------------------------------------------
# Orchestration
# ------------------------------------------------------------------

def process_knowledge_document(document_id: int) -> None:
    """
    Runs as a FastAPI BackgroundTask after a successful upload.
    Opens its own DB session — the request-scoped session used by the
    upload endpoint is already closed by the time this runs.
    """
    logger.info("background task started | document_id=%s", document_id)
    temp_path: Optional[str] = None

    with db_session() as db:
        document = get_knowledge_document_by_id(db, document_id)
        if document is None:
            logger.error("document not found, aborting | document_id=%s", document_id)
            return

        update_knowledge_document(db, document, status=IngestionStatus.PROCESSING)

        try:
            temp_path = s3_service.download_to_tempfile(
                document.file_path, suffix=f".{document.extension}"
            )
            logger.info(
                "file downloaded from S3 | document_id=%s key=%s",
                document_id, document.file_path,
            )

            logger.info(
                "parsing started | document_id=%s extension=%s",
                document_id, document.extension,
            )
            text = extract_text(temp_path, document.extension)
            logger.info("parsing completed | document_id=%s chars=%s", document_id, len(text))

            chunks = chunk_text(text)
            logger.info("chunking completed | document_id=%s chunks=%s", document_id, len(chunks))

            embeddings = generate_embeddings(chunks)
            logger.info("embeddings generated | document_id=%s count=%s", document_id, len(embeddings))

            upsert_vectors(document_id, chunks, embeddings)
            logger.info("pinecone upload completed | document_id=%s", document_id)

            update_knowledge_document(db, document, status=IngestionStatus.INDEXED)
            logger.info("processing completed | document_id=%s", document_id)

        except Exception:
            logger.exception("processing failed | document_id=%s", document_id)
            update_knowledge_document(db, document, status=IngestionStatus.FAILED)

        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)
                logger.info("temp file cleaned up | document_id=%s path=%s", document_id, temp_path)
