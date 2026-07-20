import json

from langgraph.graph import END, StateGraph

from generation.nodes import (
    compile_proposal,
    draft_section,
    needs_another_draft_pass,
    parse_requirements,
    quality_check,
    retrieve_context,
)
from generation.state import ProposalGenerationState

DEFAULT_MAX_RETRIES = 2


def build_proposal_generation_graph():
    graph = StateGraph(ProposalGenerationState)

    graph.add_node("parse_requirements", parse_requirements)
    graph.add_node("retrieve_context", retrieve_context)
    graph.add_node("draft_section", draft_section)
    graph.add_node("quality_check", quality_check)
    graph.add_node("compile_proposal", compile_proposal)

    graph.set_entry_point("parse_requirements")
    graph.add_edge("parse_requirements", "retrieve_context")
    graph.add_edge("retrieve_context", "draft_section")
    graph.add_edge("draft_section", "quality_check")
    graph.add_conditional_edges(
        "quality_check",
        needs_another_draft_pass,
        {"draft_section": "draft_section", "compile_proposal": "compile_proposal"},
    )
    graph.add_edge("compile_proposal", END)

    return graph.compile()


def _build_initial_state(
    requirement_document_id: int,
    proposal_id: int,
    user_id: int,
    category_ids: list[int] | None,
    max_retries: int,
) -> ProposalGenerationState:
    return {
        "requirement_document_id": requirement_document_id,
        "proposal_id": proposal_id,
        "user_id": user_id,
        "category_ids": category_ids,
        "requirements": {},
        "sections": [],
        "max_retries": max_retries,
        "error": None,
    }


async def run_proposal_generation(
    requirement_document_id: int,
    proposal_id: int,
    user_id: int,
    category_ids: list[int] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> ProposalGenerationState:
    graph = build_proposal_generation_graph()
    initial_state = _build_initial_state(
        requirement_document_id, proposal_id, user_id, category_ids, max_retries
    )
    return await graph.ainvoke(initial_state)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def stream_proposal_generation(
    requirement_document_id: int,
    proposal_id: int,
    user_id: int,
    category_ids: list[int] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
):
    """Server-Sent-Events generator: emits one "section" event each time a
    section's status or content changes (drafted/needs_revision/approved),
    so the frontend can render per-section progress as the graph's
    draft_section <-> quality_check loop runs, instead of waiting for the
    whole proposal to finish."""

    graph = build_proposal_generation_graph()
    initial_state = _build_initial_state(
        requirement_document_id, proposal_id, user_id, category_ids, max_retries
    )

    last_seen: dict[str, tuple] = {}
    final_state: ProposalGenerationState = initial_state

    async for state in graph.astream(initial_state, stream_mode="values"):
        final_state = state

        if state.get("error"):
            yield _sse("error", {"message": state["error"]})
            continue

        for section in state.get("sections", []):
            fingerprint = (section["status"], section.get("content"))
            if last_seen.get(section["key"]) == fingerprint:
                continue
            last_seen[section["key"]] = fingerprint

            yield _sse("section", {
                "key": section["key"],
                "title": section["title"],
                "status": section["status"],
                "content": section.get("content"),
                "citations": section.get("citations"),
                "feedback": section.get("feedback"),
            })

    if final_state.get("error"):
        yield _sse("failed", {"proposal_id": proposal_id, "message": final_state["error"]})
    else:
        yield _sse("done", {"proposal_id": proposal_id})
