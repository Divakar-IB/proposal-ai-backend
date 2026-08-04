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
    """Drafts the proposal one section at a time and streams each section's
    lifecycle as Server-Sent Events:

        event: section_start  data: {"name": "..."}
        event: section_chunk  data: {"content": "..."}   (repeated)
        event: section_done   data: {"name": "..."}
        ... (repeated per section) ...
        event: done            data: {}

    Each section is persisted to the ProposalSection table as soon as its
    draft completes, so a client disconnecting mid-stream still leaves
    earlier sections saved. On failure, an "error" event is emitted and the
    proposal is marked FAILED instead of raising into a stream that already
    sent a 200 response.

    Orchestrated by the LangGraph state machine in generation/graph.py
    (load_context -> start_section -> retrieve -> draft -> persist_section,
    looping per section, then compile_proposal). This function only drives
    the graph and translates its custom stream events into SSE lines — the
    graph's `draft` node pushes `section_chunk` events via
    langgraph.config.get_stream_writer() as the LLM streams text, which is
    why stream_mode="custom" surfaces them here in real time."""

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
