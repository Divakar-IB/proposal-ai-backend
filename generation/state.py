from typing import Any, Optional, TypedDict


class SectionState(TypedDict):
    key: str
    title: str
    query_fields: str
    drafting_note: Optional[str]
    retrieved_chunks: list[dict[str, Any]]
    content: Optional[str]
    citations: list[dict[str, Any]]
    status: str  # ProposalSectionStatus value
    feedback: Optional[str]


class ProposalGenerationState(TypedDict):
    requirement_document_id: int
    proposal_id: int
    user_id: int
    requirements: dict[str, Any]
    sections: list[SectionState]
    max_retries: int
    error: Optional[str]

    # Working fields used by generation/graph.py's node functions.
    page_count: int
    generation_mode: str  # GenerationMode value
    requirements_json: str
    proposal_title: str
    client_name: str
    additional_context: Optional[str]
    # section key -> word budget for that section, summing to the requested
    # page_count's word budget (see generation/length_budget.py).
    word_targets: dict[str, int]
    has_knowledge: bool
    # Prefetched retrieval results: section key -> {chunks, document_by_id}
    section_retrievals: dict[str, dict[str, Any]]
    # Current position in the linear graph's per-section loop
    current_section_index: int
    # The section state being drafted in the current iteration
    current_section: SectionState
    # Populated as each section finishes. Sections complete in order since the
    # graph is linear (one section at a time).
    persisted_sections: list[dict[str, Any]]  # {title, content, order_index}
    markdown_path: Optional[str]
