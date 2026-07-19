from database.crud import get_proposal_by_id, update_proposal
from database.database import db_session
from database.db_enum import ProposalStatus
from generation.graph import run_proposal_generation
from utilities.logger import get_logger

logger = get_logger(__name__)


async def generate_proposal(
    requirement_document_id: int,
    proposal_id: int,
    user_id: int,
    category_ids: list[int] | None = None,
) -> None:
    """
    Runs as a background task (Arq job) after POST /proposals/generate creates
    the Proposal row. Drives the LangGraph flow end to end; the graph's own
    compile_proposal node persists sections + markdown, this wrapper only
    owns overall Proposal status and failure handling.
    """
    logger.info("proposal generation started | proposal_id=%s", proposal_id)

    try:
        final_state = await run_proposal_generation(
            requirement_document_id=requirement_document_id,
            proposal_id=proposal_id,
            user_id=user_id,
            category_ids=category_ids,
        )

        if final_state.get("error"):
            async with db_session() as db:
                proposal = await get_proposal_by_id(db, proposal_id)
                if proposal:
                    await update_proposal(
                        db, proposal, status=ProposalStatus.FAILED, error_message=final_state["error"]
                    )
            logger.error("proposal generation failed | proposal_id=%s error=%s", proposal_id, final_state["error"])
            return

        logger.info("proposal generation completed | proposal_id=%s", proposal_id)

    except Exception as error:
        logger.exception("proposal generation failed | proposal_id=%s", proposal_id)
        async with db_session() as db:
            proposal = await get_proposal_by_id(db, proposal_id)
            if proposal:
                await update_proposal(db, proposal, status=ProposalStatus.FAILED, error_message=str(error))
