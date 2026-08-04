from typing import Any, TypedDict


class SectionState(TypedDict):
    key: str
    title: str
    query_fields: str
    drafting_note: str | None
    retrieved_chunks: list[dict[str, Any]]
    content: str | None
    citations: list[dict[str, Any]]
    status: str  # ProposalSectionStatus value
    feedback: str | None


class ProposalGenerationState(TypedDict):
    requirement_document_id: int
    proposal_id: int
    user_id: int
    requirements: dict[str, Any]
    sections: list[SectionState]
    max_retries: int
    error: str | None

    # Working fields used by generation/graph.py's node functions.
    page_count: int
    generation_mode: str  # GenerationMode value
    requirements_json: str
    proposal_title: str
    client_name: str
    additional_context: str | None
    # section key -> word budget for that section, summing to the requested
    # page_count's word budget (see generation/length_budget.py).
    word_targets: dict[str, int]
    has_knowledge: bool
    current_section_index: int
    current_section: SectionState | None
    persisted_sections: list[dict[str, Any]]  # {title, content, order_index}
    markdown_path: str | None
