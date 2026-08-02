from typing import Optional

from chunking.markdown_splitter import split_by_headers
from chunking.models import Chunk
from chunking.recursive_splitter import (
    DEFAULT_CHUNK_OVERLAP_TOKENS,
    DEFAULT_CHUNK_SIZE_TOKENS,
    split_oversized_section,
)
from chunking.tokenization import count_tokens
from extraction.base import ExtractedDocument


def chunk_document(
    document: ExtractedDocument,
    root_prefix: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    """header-split -> sub-split oversized sections -> breadcrumb-prefix -> Chunk objects.

    root_prefix (e.g. "Category > Document Title") is prepended to every
    breadcrumb so retrieval/citations carry full context, not just in-document headings.
    """

    sections = split_by_headers(document.markdown)

    chunks: list[Chunk] = []
    for section_content, heading_breadcrumb in sections:
        full_breadcrumb = " > ".join(part for part in (root_prefix, heading_breadcrumb) if part)

        for piece in split_oversized_section(section_content, chunk_size, chunk_overlap):
            prefixed = f"{full_breadcrumb}: {piece}" if full_breadcrumb else piece
            chunks.append(Chunk(
                content=prefixed,
                breadcrumb=full_breadcrumb,
                chunk_index=len(chunks),
                token_count=count_tokens(prefixed),
            ))

    return chunks
