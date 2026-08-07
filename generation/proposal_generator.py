import json
from typing import AsyncIterator

from database.crud import get_proposal_by_id, update_proposal
from database.database import db_session
from database.db_enum import GenerationMode, ProposalStatus
from generation.graph import PROPOSAL_GENERATION_GRAPH
from utilities.logger import get_logger

logger = get_logger(__name__)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def generate_proposal_stream(
    proposal_id: int,
    page_count: int,
    generation_mode: GenerationMode,
) -> AsyncIterator[str]:
    """Drafts the proposal and streams each section's lifecycle as
    Server-Sent Events:

        event: section_start  data: {"name": "..."}
        event: section_chunk  data: {"content": "...", "name": "..."}  (repeated)
        event: section_done   data: {"name": "..."}
        ... (repeated per section) ...
        event: done            data: {}

    `section_chunk` carries the section `name` alongside the text because
    sections can be drafted concurrently (config.generation.concurrency), and
    interleaved chunks would otherwise be unattributable. At the default
    concurrency of 1 the event order is identical to the strictly sequential
    behaviour this had before.

    Each section is persisted to the ProposalSection table as soon as its
    draft completes, so a client disconnecting mid-stream still leaves
    earlier sections saved. On failure, an "error" event is emitted and the
    proposal is marked FAILED instead of raising into a stream that already
    sent a 200 response — sections that had already completed stay persisted.

    Orchestrated by the LangGraph state machine in generation/graph.py
    (load_context -> draft_sections -> compile_proposal). `draft_sections`
    fans out per section under an asyncio.Semaphore; each section pushes its
    events via langgraph.config.get_stream_writer() as the LLM streams text,
    which is why stream_mode="custom" surfaces them here in real time."""

    initial_state = {
        "proposal_id": proposal_id,
        "page_count": page_count,
        "generation_mode": generation_mode,
    }

    try:
        async for chunk in PROPOSAL_GENERATION_GRAPH.astream(initial_state, stream_mode="custom"):
            yield _sse(chunk["event"], chunk["data"])
    except Exception as error:
        logger.exception("proposal generation failed | proposal_id=%s", proposal_id)
        async with db_session() as db:
            proposal = await get_proposal_by_id(db, proposal_id)
            if proposal:
                await update_proposal(db, proposal, status=ProposalStatus.FAILED, error_message=str(error))
        yield _sse("error", {"message": str(error)})
        return

    yield _sse("done", {})
