from dataclasses import dataclass


@dataclass
class Chunk:
    """A single final chunk, ready to embed — breadcrumb already prefixed into content."""

    content: str
    breadcrumb: str
    chunk_index: int
    token_count: int
