from typing import Any, Optional, TypedDict, NotRequired


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
    proposal_id: int
    page_count: int
    generation_mode: str  # GenerationMode value

    # Set by load_context
    user_id: int
    requirements: dict[str, Any]
    requirements_json: str
    proposal_title: str
    client_name: str
    additional_context: Optional[str]
    word_targets: dict[str, int]
    has_knowledge: bool
    section_retrievals: dict[str, dict[str, Any]]

    # Per-section loop state
    current_section_index: int
    current_section: SectionState

    # Output
    persisted_sections: list[dict[str, Any]]  # {title, content, order_index}
    markdown_path: Optional[str]

    # Legacy fields (may be unused)
    requirement_document_id: NotRequired[int]
    sections: NotRequired[list[SectionState]]
    max_retries: NotRequired[int]
    error: NotRequired[Optional[str]]
