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
    retry_count: int
    feedback: Optional[str]
    confidence_score: Optional[float]
    review_flag: bool


class ProposalGenerationState(TypedDict):
    requirement_document_id: int
    proposal_id: int
    user_id: int
    category_ids: Optional[list[int]]
    requirements: dict[str, Any]
    sections: list[SectionState]
    max_retries: int
    error: Optional[str]
