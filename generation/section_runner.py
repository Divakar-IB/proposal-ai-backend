"""One section's full retrieve -> draft -> persist chain, as a single awaitable.

This is the unit the concurrency cap applies to. Keeping the three steps
together per section (rather than running all retrievals, then all drafts) is
what preserves the existing guarantee that a section is persisted the moment it
finishes, so a client disconnecting mid-stream keeps everything completed so
far.

Sections may finish out of order. Nothing downstream depends on completion
order — `assemble_markdown` sorts by `order_index` — but every SSE event
carries the section name so the client can attribute streamed text to the right
section while several are in flight.
"""

import asyncio
import time
from typing import Any, AsyncIterator, Callable, Iterator, Optional

from database.crud import create_proposal_sections
from database.database import db_session
from database.db_enum import ProposalSectionStatus
from database.models import ProposalSection
from generation.nodes import (
    build_draft_messages,
    draft_one_section_stream,
    log_section_outcome,
    retrieve_chunks_for_section,
    section_citations,
    validate_section_outcome,
)
from generation.rate_limit import governor, run_with_rate_limit_retry
from generation.token_budget import (
    clamp_completion_tokens,
    completion_tokens_for,
    describe_budget,
    estimate_prompt_tokens,
    prompt_exceeds_ceiling,
)
from llm.chat_client import StreamOutcome
from utilities.logger import get_logger

logger = get_logger(__name__)


class SectionRestartedError(RuntimeError):
    """A section failed after it had already streamed visible text.

    Not retried: the client has already rendered those tokens, and re-running
    the section would append a second copy of the body. Raised so the whole
    generation fails cleanly instead of shipping duplicated text.
    """


async def _aiter_blocking(make_iterator: Callable[[], Iterator[str]], label: str) -> AsyncIterator[str]:
    """Bridges a blocking synchronous generator into an async iterator.

    Required for live token streaming. `draft_one_section_stream` is a sync
    generator that blocks on socket reads from the LLM; iterating it directly
    inside an async node never yields to the event loop, so LangGraph's stream
    consumer cannot drain the writer queue and every token of a section is
    flushed in one burst when the node finally returns — the client sees a
    lump per section instead of text appearing as it is generated.

    Running the producer in a worker thread and awaiting each item hands
    control back to the event loop per token, so the SSE line goes out
    immediately. It also keeps the loop free while the LLM socket blocks,
    instead of stalling every other request in the process.

    Ordering note: `call_soon_threadsafe` callbacks run in the order they were
    scheduled, and the `_DONE` sentinel is scheduled from the producer's
    `finally` — after every item. So reaching the sentinel means the queue has
    been fully drained; a tail cannot be silently lost ahead of it. What *can*
    happen is the consumer abandoning the iterator early (client disconnect),
    which is logged below rather than passing unnoticed.
    """

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    done = object()
    produced = 0
    consumed = 0

    def produce() -> None:
        nonlocal produced
        try:
            for item in make_iterator():
                produced += 1
                loop.call_soon_threadsafe(queue.put_nowait, item)
        except BaseException as error:  # re-raised on the consumer side below
            loop.call_soon_threadsafe(queue.put_nowait, error)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, done)

    producer = loop.run_in_executor(None, produce)
    drained = False
    try:
        while True:
            item = await queue.get()
            if item is done:
                drained = True
                break
            if isinstance(item, BaseException):
                logger.warning(
                    "draft stream raised after %s/%s deltas | section=%s error=%s: %s",
                    consumed,
                    produced,
                    label,
                    type(item).__name__,
                    item,
                )
                raise item
            consumed += 1
            yield item
    finally:
        # Always awaited, so the worker thread can never outlive the iterator
        # and write into a queue nobody reads.
        await producer
        if not drained:
            logger.warning(
                "draft stream abandoned before completion | section=%s consumed=%s produced=%s queued=%s",
                label,
                consumed,
                produced,
                queue.qsize(),
            )


async def _stream_draft(
    section_state: dict[str, Any],
    requirements_json: str,
    max_completion_tokens: int,
    writer: Callable[[dict], Any],
) -> tuple[str, StreamOutcome]:
    """One drafting attempt: stream the body out as SSE and collect it."""

    outcome = StreamOutcome()
    parts: list[str] = []

    try:
        async for delta in _aiter_blocking(
            lambda: draft_one_section_stream(
                section_state,
                requirements_json,
                max_completion_tokens=max_completion_tokens,
                outcome=outcome,
            ),
            section_state["title"],
        ):
            parts.append(delta)
            writer(
                {
                    "event": "section_chunk",
                    # `name` added so a client can attribute chunks while
                    # several sections stream concurrently. Additive: the
                    # existing `content` key is unchanged.
                    "data": {"content": delta, "name": section_state["title"]},
                }
            )
    except Exception as error:
        if parts:
            raise SectionRestartedError(
                f"section {section_state['title']!r} failed after streaming "
                f"{sum(len(part) for part in parts)} characters, so it cannot be safely "
                f"retried (the client has already rendered them): {error}"
            ) from error
        raise

    return "".join(parts).strip(), outcome


async def run_section(
    proposal_id: int,
    order_index: int,
    section_state: dict[str, Any],
    requirements: dict[str, Any],
    requirements_json: str,
    word_target: int,
    has_knowledge: bool,
    writer: Callable[[dict], Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Retrieve, draft and persist one section. Returns its persisted shape.

    The semaphore is held across the whole chain rather than only the LLM call:
    retrieval also costs an embedding request and a Pinecone query, and letting
    twelve of those run while drafting is capped at one defeats the point of
    having a cap.
    """

    async with semaphore:
        started = time.perf_counter()
        writer({"event": "section_start", "data": {"name": section_state["title"]}})

        async with db_session() as db:
            section_state["retrieved_chunks"] = await retrieve_chunks_for_section(
                db,
                section_state,
                requirements,
                has_knowledge,
            )
        chunks_retrieved = len(section_state["retrieved_chunks"])

        # Size the request only after retrieval, since the retrieved context is
        # the largest and most variable part of the prompt.
        messages = build_draft_messages(section_state, requirements_json)
        prompt_tokens = estimate_prompt_tokens(messages)
        desired = completion_tokens_for(word_target)
        max_completion_tokens, was_clamped = clamp_completion_tokens(prompt_tokens, desired)
        budget_note = describe_budget(prompt_tokens, max_completion_tokens)

        if prompt_exceeds_ceiling(prompt_tokens):
            # Not clampable: no completion size makes this request legal. Sent
            # anyway because Groq's tokenizer is the authority and our estimate
            # may be pessimistic, but logged loudly first so a 413 arriving next
            # is already explained.
            logger.error(
                "prompt alone exceeds the per-request token ceiling | section=%s %s "
                "chunks=%s — expect a 413. The retrieved-context block dominates the prompt: "
                "reduce generation/nodes.py::TOP_K_SECTION_CHUNKS or raise "
                "groq.tokens_per_minute to match the account tier.",
                section_state["title"],
                budget_note,
                chunks_retrieved,
            )
        elif was_clamped:
            logger.warning(
                "section token cap clamped by the TPM ceiling | section=%s word_target=%s "
                "wanted=%s granted=%s %s — this section will run short. Lower page_count, "
                "reduce TOP_K_SECTION_CHUNKS, or raise groq.tokens_per_minute.",
                section_state["title"],
                word_target,
                desired,
                max_completion_tokens,
                budget_note,
            )

        await governor.acquire(prompt_tokens + max_completion_tokens, section_state["title"])

        content, outcome = await run_with_rate_limit_retry(
            lambda: _stream_draft(section_state, requirements_json, max_completion_tokens, writer),
            label=section_state["title"],
        )
        governor.update_from_headers(outcome.rate_limit_headers)

        log_section_outcome(
            section_state["title"],
            word_target,
            chunks_retrieved,
            max_completion_tokens,
            budget_note,
            outcome,
            time.perf_counter() - started,
        )

        # Before persisting, not after: an empty or truncated section must not
        # reach the table at all.
        validate_section_outcome(section_state["title"], content, outcome, max_completion_tokens)

        section_state["content"] = content
        section_state["citations"] = section_citations(section_state)
        section_state["status"] = ProposalSectionStatus.APPROVED.value

        async with db_session() as db:
            await create_proposal_sections(
                db,
                [
                    ProposalSection(
                        proposal_id=proposal_id,
                        section_key=section_state["key"],
                        title=section_state["title"],
                        order_index=order_index,
                        content=section_state["content"],
                        citations=section_state["citations"],
                        status=ProposalSectionStatus.APPROVED,
                    )
                ],
            )

        writer({"event": "section_done", "data": {"name": section_state["title"]}})

        return {
            "title": section_state["title"],
            "content": section_state["content"],
            "order_index": order_index,
        }


def unwrap_section_error(error: BaseException, section_title: Optional[str] = None) -> str:
    """Message for the SSE `error` event / Proposal.error_message.

    Names the section, because with concurrent drafting the failing section is
    no longer simply "the last one that started".
    """

    prefix = f"section {section_title!r}: " if section_title else ""
    return f"{prefix}{type(error).__name__}: {error}"
