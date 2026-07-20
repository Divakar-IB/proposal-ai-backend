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
    # Carried through from the source page's ExtractedPage — surfaced as
    # Pinecone metadata (see vectorstore/knowledge_store.py) so retrieval can
    # filter/weight by how the source text was produced and how confident OCR was.
    confidence: Optional[float] = None
    source_type: Optional[str] = None
