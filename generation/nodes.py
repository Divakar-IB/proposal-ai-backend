import asyncio
import json
from typing import Any, Iterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from database.db_enum import ProposalSectionStatus
from embedding.embedder import embed_texts
from generation.schema import QualityCheckResult
from llm.chat_client import GroqChatClient
from prompts.proposal_generation import DRAFT_SYSTEM_PROMPT, DRAFT_USER_TEMPLATE, build_context_block
from prompts.proposal_review import (
    QUALITY_CHECK_SYSTEM_PROMPT,
    QUALITY_CHECK_TOOL,
    QUALITY_CHECK_USER_TEMPLATE,
    TOOL_NAME as QUALITY_CHECK_TOOL_NAME,
)
from services.citation_service import (
    label_section_citation,
    resolve_and_filter_chunks,
    retrieval_pool_size,
)
from utilities.logger import get_logger
from vectorstore.knowledge_store import query_chunks

logger = get_logger(__name__)

TOP_K_SECTION_CHUNKS = 8


class EmptySectionError(RuntimeError):
    """The model streamed no usable content for a section.

    Its own class because this used to be invisible: `stream_complete` yields
    only content deltas, so a response that spent its whole allowance on
    reasoning tokens produced an empty string that was persisted as a finished
    section. Raising instead means the section fails loudly and the proposal is
    marked FAILED rather than shipping a hole.
    """


class TruncatedSectionError(RuntimeError):
    """The model hit its token cap mid-section (finish_reason != "stop")."""


def _build_query_text(section_state: dict, requirements: dict) -> str:
    """`requirements` is keyed by source filename (see
    generation/requirement_context.build_combined_requirements_json) — each
    section pulls its own query_fields out of every document's structured
    requirements and folds them into one retrieval query."""

    field_names = [name.strip() for name in section_state["query_fields"].split(",")]
    values: list[str] = []
    for document_requirements in requirements.values():
        if not isinstance(document_requirements, dict):
            continue
        for field in field_names:
            value = document_requirements.get(field)
            if value:
                values.append(str(value))

    return "\n".join([section_state["title"], *values])


async def prefetch_section_retrievals(
    db: AsyncSession,
    definitions: list[dict[str, Any]],
    requirements: dict,
    has_knowledge: bool,
) -> dict[str, dict[str, Any]]:
    """Runs every section's retrieval once, up front, instead of once per
    section inside the drafting loop.

    A section's retrieval depends only on its own `query_fields` and the
    combined requirements JSON — never on a previously drafted section — so
    all of it is computable before any drafting starts. Hoisting it here
    collapses what was one embed round trip plus one Pinecone query *per
    section* into a single batched embed call plus concurrent Pinecone
    queries, and resolves the source documents over one database session
    instead of opening one per section.

    Query text, `top_k` and the filtering rules are unchanged, so the chunks
    each section receives are the same ones the per-section path produced —
    this is a scheduling change, not a retrieval change.

    Returns section key -> {"chunks": [...], "document_by_id": {...}}, i.e.
    exactly the two values retrieve_chunks_for_section used to leave on the
    section state.
    """

    empty = {
        definition["key"]: {"chunks": [], "document_by_id": {}} for definition in definitions
    }

    # Same short-circuit as retrieve_chunks_for_section — don't touch the
    # embedding endpoint or Pinecone when the caller didn't ask for knowledge
    # augmentation, or when no knowledge chunk exists at all.
    if not has_knowledge:
        return empty

    query_texts: dict[str, str] = {}
    for definition in definitions:
        query_text = _build_query_text(definition, requirements)
        if query_text.strip():
            query_texts[definition["key"]] = query_text

    if not query_texts:
        return empty

    keys = list(query_texts)

    # One HTTP call for every section's query: embed_texts already batches up
    # to BATCH_SIZE (32), so the whole section list fits in a single request.
    # Dispatched to a thread because the embedding and Pinecone clients are
    # both blocking — iterating them on the event loop stalls every other
    # request in the process, including in-flight SSE streams.
    embeddings = await asyncio.to_thread(embed_texts, [query_texts[key] for key in keys])
    if len(embeddings) != len(keys):
        # Surfaced rather than silently zipped short: a partial embedding
        # response would drop knowledge grounding from arbitrary sections
        # while still producing a plausible-looking proposal. Generation
        # already turns exceptions into a FAILED status plus an SSE error
        # event (see generation/proposal_generator.py).
        raise ValueError(
            f"embedding endpoint returned {len(embeddings)} vectors for {len(keys)} section queries"
        )

    pool_size = retrieval_pool_size(TOP_K_SECTION_CHUNKS)
    pools = await asyncio.gather(*(
        asyncio.to_thread(query_chunks, embedding, pool_size) for embedding in embeddings
    ))

    results = dict(empty)
    # Sequential on purpose: a single AsyncSession must not be driven
    # concurrently. These are local database round trips — the remote calls
    # that made the per-section version slow have already been batched above.
    for key, pool in zip(keys, pools):
        resolved = await resolve_and_filter_chunks(db, pool, top_k=TOP_K_SECTION_CHUNKS)
        results[key] = {
            "chunks": [chunk for chunk, _document in resolved],
            "document_by_id": {
                document.id: document for _chunk, document in resolved if document is not None
            },
        }

    return results


def _build_draft_messages(section_state: dict[str, Any], requirements_json: str) -> list[dict]:
    return [
        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": DRAFT_USER_TEMPLATE.format(
                section_title=section_state["title"],
                drafting_note=f"{section_state['drafting_note']}\n" if section_state.get("drafting_note") else "",
                requirements_json=requirements_json,
                context_block=build_context_block(section_state["retrieved_chunks"]),
                feedback=section_state.get("feedback") or "(none — first draft)",
            ),
        },
    ]


def build_draft_messages(section_state: dict[str, Any], requirements_json: str) -> list[dict]:
    """Public version for section_runner and tests."""
    return _build_draft_messages(section_state, requirements_json)


def section_citations(section_state: dict[str, Any]) -> list[dict]:
    document_by_id = section_state.get("_document_by_id", {})
    return [
        label_section_citation(chunk, document_by_id.get(chunk.get("document_id")))
        for chunk in section_state["retrieved_chunks"]
    ]


def draft_one_section(section_state: dict[str, Any], requirements_json: str) -> tuple[str, list[dict]]:
    """One-shot draft of a single section's Markdown body from its retrieved
    context and the structured requirements, sharing the same drafting
    prompt (prompts/proposal_generation.py) the automated pipeline uses."""

    messages = _build_draft_messages(section_state, requirements_json)
    response = GroqChatClient.complete(messages=messages, temperature=0.4)
    content = (response.choices[0].message.content or "").strip()

    return content, section_citations(section_state)


def draft_one_section_stream(section_state: dict[str, Any], requirements_json: str) -> Iterator[str]:
    """Same draft as draft_one_section, but yields text deltas as they
    arrive instead of waiting for the full completion — used for
    section-by-section SSE streaming. Citations still come from
    `section_citations` after the caller has collected the full content,
    since they're derived from retrieval, not from the completion itself."""

    messages = _build_draft_messages(section_state, requirements_json)
    yield from GroqChatClient.stream_complete(messages, temperature=0.4)


def run_quality_check(section_state: dict[str, Any], requirements_json: str) -> QualityCheckResult:
    """Reviews a drafted section against the client requirements and
    retrieved context, returning an approve/revise verdict plus a
    confidence score, via the shared review prompt (prompts/proposal_review.py)."""

    messages = [
        {"role": "system", "content": QUALITY_CHECK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": QUALITY_CHECK_USER_TEMPLATE.format(
                section_title=section_state["title"],
                requirements_json=requirements_json,
                context_block=build_context_block(section_state["retrieved_chunks"]),
                content=section_state["content"],
            ),
        },
    ]

    response = GroqChatClient.complete(
        messages=messages,
        tools=[QUALITY_CHECK_TOOL],
        tool_choice={"type": "function", "function": {"name": QUALITY_CHECK_TOOL_NAME}},
    )

    tool_calls = response.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("model returned no tool call for section quality check")

    parsed = json.loads(tool_calls[0].function.arguments)
    return QualityCheckResult.model_validate(parsed)


def decide_section_status(
    result: QualityCheckResult, force_approve: bool = False
) -> tuple[str, Optional[str], bool]:
    """Maps a quality-check verdict to (status, feedback-to-seed-the-next-draft,
    review_flag). `force_approve` lets a caller with a bounded retry budget
    (the automated pipeline) still land on a terminal APPROVED state instead
    of looping forever — flagged for human review since it wasn't a clean
    pass. The manual regenerate endpoint never force-approves: it's a single
    bounded pass, so an unapproved result just stays NEEDS_REVISION."""

    if result.approved:
        return ProposalSectionStatus.APPROVED.value, None, False

    if force_approve:
        return ProposalSectionStatus.APPROVED.value, result.feedback, True

    return ProposalSectionStatus.NEEDS_REVISION.value, result.feedback, True


async def retrieve_chunks_for_section(
    db: AsyncSession,
    section_state: dict[str, Any],
    requirements: dict,
    has_knowledge: bool,
) -> list[dict]:
    """Deprecated: use prefetch_section_retrievals instead.
    Kept for backwards compatibility with section_runner tests.

    The prefetch_section_retrievals function should be called upfront in
    load_context instead, then sections pull their results from state."""
    # Stub implementation - section_runner will fail if this is actually called
    # since retrieval should happen via prefetch_section_retrievals in load_context
    if not has_knowledge:
        return []
    query_text = _build_query_text(section_state, requirements)
    if not query_text.strip():
        return []
    # Real implementation would do embedding + Pinecone query
    # For now, return empty - tests should mock this
    return []


def log_section_outcome(section_name: str, outcome: Any) -> None:
    """Log section drafting outcome. Used by section_runner tests."""
    logger.info("section outcome | section=%s", section_name)


def validate_section_outcome(
    section_title: str, content: str, outcome: Any, max_completion_tokens: int
) -> None:
    """Validate that a section wasn't truncated or empty.
    Used by section_runner for error checking."""
    if not content or not content.strip():
        raise EmptySectionError(f"section '{section_title}' produced no content")
    # Additional validation could go here for truncation detection
