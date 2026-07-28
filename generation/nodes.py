import json
from typing import Any, Iterator, Optional

from database.db_enum import ProposalSectionStatus
from embedding.embedder import embed_query
from generation.schema import QualityCheckResult
from llm.chat_client import GroqChatClient
from prompts.proposal_generation import DRAFT_SYSTEM_PROMPT, DRAFT_USER_TEMPLATE, build_context_block
from prompts.proposal_review import (
    QUALITY_CHECK_SYSTEM_PROMPT,
    QUALITY_CHECK_TOOL,
    QUALITY_CHECK_USER_TEMPLATE,
    TOOL_NAME as QUALITY_CHECK_TOOL_NAME,
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
    section_state: dict[str, Any],
    requirements: dict,
    category_ids: Optional[list[int]],
    has_knowledge: bool,
) -> list[dict]:
    """Per-section retrieval — each section queries the knowledge base with
    its own query_fields-derived text, scoped to the proposal's
    category_ids, rather than one retrieval pass shared across the whole
    document."""

    if not has_knowledge:
        return []

    query_text = _build_query_text(section_state, requirements)
    if not query_text.strip():
        return []

    query_embedding = embed_query(query_text)
    return query_chunks(query_embedding, top_k=TOP_K_SECTION_CHUNKS, category_ids=category_ids)


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
    return [
        {
            "breadcrumb": chunk["breadcrumb"],
            "source_filename": chunk.get("source_filename"),
        }
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
