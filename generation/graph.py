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


async def run_proposal_generation(
    requirement_document_id: int,
    proposal_id: int,
    user_id: int,
    category_ids: list[int] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> ProposalGenerationState:
    graph = build_proposal_generation_graph()

    initial_state: ProposalGenerationState = {
        "requirement_document_id": requirement_document_id,
        "proposal_id": proposal_id,
        "user_id": user_id,
        "category_ids": category_ids,
        "requirements": {},
        "sections": [],
        "max_retries": max_retries,
        "error": None,
    }

    return await graph.ainvoke(initial_state)
