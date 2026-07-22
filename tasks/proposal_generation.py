from database.crud import get_proposal_by_id, update_proposal
from database.database import db_session
from database.db_enum import GenerationMode, ProposalStatus
from generation.proposal_generator import generate_proposal_stream
from utilities.logger import get_logger

logger = get_logger(__name__)


async def generate_proposal(
    proposal_id: int,
    page_count: int,
    generation_mode: GenerationMode,
) -> None:
    """Runs as a background task (Arq job) — drives the same generator the
    streaming API uses, just consuming its output fully instead of forwarding
    chunks to an HTTP client. The generator persists sections/markdown and
    handles its own FAILED status update on error; this wrapper is a backstop
    for failures raised before the generator gets that far (e.g. proposal
    not found)."""

    logger.info("proposal generation started | proposal_id=%s", proposal_id)

    try:
        async for _ in generate_proposal_stream(proposal_id, page_count, generation_mode):
            pass
        logger.info("proposal generation completed | proposal_id=%s", proposal_id)

    except Exception as error:
        logger.exception("proposal generation failed | proposal_id=%s", proposal_id)
        async with db_session() as db:
            proposal = await get_proposal_by_id(db, proposal_id)
            if proposal:
                await update_proposal(db, proposal, status=ProposalStatus.FAILED, error_message=str(error))
