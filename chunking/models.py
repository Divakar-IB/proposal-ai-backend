from dataclasses import dataclass
from typing import Optional


@dataclass
class Chunk:
    """A single final chunk, ready to embed — breadcrumb already prefixed into content."""

    content: str
    breadcrumb: str
    chunk_index: int
    token_count: int
    page_number: Optional[int] = None
