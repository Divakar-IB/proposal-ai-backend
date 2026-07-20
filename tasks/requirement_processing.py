from pathlib import Path
from typing import Optional

from database.crud import get_requirement_document_by_id, update_requirement_document
from database.database import db_session
from database.db_enum import DocumentStatus
from extraction.factory import run_extraction
from requirements_parsing.parser import parse_requirements
from utilities.logger import get_logger
from utilities.s3_service import S3Service

logger = get_logger(__name__)
s3_service = S3Service()


async def process_requirement_document(document_id: int) -> None:
    """
    Runs as a background task (Arq job) after a successful upload.
    extract -> structured parse -> Postgres storage.
    Deliberately does NOT touch Pinecone — structured output becomes the
    query input for retrieval, it is never embedded itself.
    """
    logger.info("background task started | document_id=%s", document_id)
    temp_path: Optional[str] = None

    async with db_session() as db:
        document = await get_requirement_document_by_id(db, document_id)
        if document is None:
            logger.error("document not found, aborting | document_id=%s", document_id)
            return

        await update_requirement_document(db, document, status=DocumentStatus.EXTRACTING)

        try:
            temp_path = s3_service.download_to_tempfile(
                document.file_path, suffix=f".{document.extension}"
            )
            logger.info(
                "file downloaded from S3 | document_id=%s key=%s",
                document_id, document.file_path,
            )

            extracted = run_extraction(temp_path, document.file_name, document.extension)
            logger.info(
                "extraction completed | document_id=%s chars=%s pages=%s",
                document_id, len(extracted.markdown), len(extracted.pages),
            )
            await update_requirement_document(
                db, document,
                extracted_markdown=extracted.markdown,
                extracted_pages=extracted.to_page_records(),
            )

            requirements = parse_requirements(extracted.markdown)
            logger.info("structured parse completed | document_id=%s", document_id)

            await update_requirement_document(
                db, document,
                parsed_data=requirements.model_dump(),
                status=DocumentStatus.PARSED,
            )
            logger.info("processing completed | document_id=%s", document_id)

        except Exception:
            logger.exception("processing failed | document_id=%s", document_id)
            await update_requirement_document(db, document, status=DocumentStatus.FAILED)

        finally:
            if temp_path:
                Path(temp_path).unlink(missing_ok=True)
                logger.info("temp file cleaned up | document_id=%s path=%s", document_id, temp_path)
