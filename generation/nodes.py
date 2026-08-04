import json
from collections.abc import Iterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from database.db_enum import ProposalSectionStatus
from embedding.embedder import embed_query
from generation.schema import QualityCheckResult
from llm.chat_client import GroqChatClient
from prompts.proposal_generation import DRAFT_SYSTEM_PROMPT, DRAFT_USER_TEMPLATE, build_context_block
from prompts.proposal_review import (
    QUALITY_CHECK_SYSTEM_PROMPT,
    QUALITY_CHECK_TOOL,
    QUALITY_CHECK_USER_TEMPLATE,
)
from prompts.proposal_review import (
    TOOL_NAME as QUALITY_CHECK_TOOL_NAME,
)
from services.citation_service import (
    label_section_citation,
    resolve_and_filter_chunks,
    retrieval_pool_size,
)
from vectorstore.knowledge_store import query_chunks

TOP_K_SECTION_CHUNKS = 8


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


async def retrieve_chunks_for_section(
    db: AsyncSession,
    section_state: dict[str, Any],
    requirements: dict,
    has_knowledge: bool,
) -> list[dict]:
    """Per-section retrieval — each section queries the knowledge base with
    its own query_fields-derived text, rather than one retrieval pass shared
    across the whole document.

    Excludes chunks sourced from a previously approved proposal by default
    (see services.citation_service.resolve_and_filter_chunks) — otherwise
    another client's approved content could get pasted verbatim into this
    draft. The resolved source documents are stashed on section_state so
    section_citations (below) can label them without a second lookup."""

    if not has_knowledge:
        return []

    query_text = _build_query_text(section_state, requirements)
    if not query_text.strip():
        return []

    query_embedding = embed_query(query_text)
    pool = query_chunks(query_embedding, top_k=retrieval_pool_size(TOP_K_SECTION_CHUNKS))

    resolved = await resolve_and_filter_chunks(db, pool, top_k=TOP_K_SECTION_CHUNKS)
    section_state["_document_by_id"] = {document.id: document for _chunk, document in resolved if document is not None}
    return [chunk for chunk, _document in resolved]


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


def decide_section_status(result: QualityCheckResult, force_approve: bool = False) -> tuple[str, str | None, bool]:
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
