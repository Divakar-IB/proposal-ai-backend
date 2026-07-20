import asyncio

from arq.connections import RedisSettings

from config import config
from extraction.ocr_engine import StructuredOCREngine
from tasks.document_processing import process_knowledge_document
from tasks.proposal_generation import generate_proposal
from tasks.requirement_processing import process_requirement_document
from utilities.logger import get_logger

logger = get_logger(__name__)


async def on_startup(ctx) -> None:
    """Pre-warms PPStructureV3 (layout/OCR/table/formula models — a first-run,
    multi-GB download) at worker boot instead of on the first scanned-page job,
    so that job isn't the one that silently eats several minutes."""

    logger.info("pre-warming PPStructureV3 engine")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, StructuredOCREngine.get_engine)
    logger.info("PPStructureV3 engine ready")


async def knowledge_document_job(ctx, document_id: int) -> None:
    await process_knowledge_document(document_id)


async def requirement_document_job(ctx, document_id: int) -> None:
    await process_requirement_document(document_id)


async def proposal_generation_job(
    ctx, requirement_document_id: int, proposal_id: int, user_id: int, category_ids: list[int] | None = None
) -> None:
    await generate_proposal(requirement_document_id, proposal_id, user_id, category_ids)


class WorkerSettings:
    """Run with: arq tasks.arq_worker.WorkerSettings"""

    functions = [knowledge_document_job, requirement_document_job, proposal_generation_job]
    on_startup = on_startup
    redis_settings = RedisSettings(
        host=config.redis.host,
        port=config.redis.port,
        database=config.redis.db,
    )
    # Extraction/OCR/generation jobs can run long — keep the default job timeout
    # generous rather than letting large documents get killed mid-pipeline.
    job_timeout = 900
