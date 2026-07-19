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

    page_offsets = _build_page_offsets(document)
    sections = split_by_headers(document.markdown)

    chunks: list[Chunk] = []
    for section_content, heading_breadcrumb in sections:
        full_breadcrumb = " > ".join(part for part in (root_prefix, heading_breadcrumb) if part)
        page_number = _locate_page(document.markdown, section_content, page_offsets)

        for piece in split_oversized_section(section_content, chunk_size, chunk_overlap):
            prefixed = f"{full_breadcrumb}: {piece}" if full_breadcrumb else piece
            chunks.append(Chunk(
                content=prefixed,
                breadcrumb=full_breadcrumb,
                chunk_index=len(chunks),
                token_count=count_tokens(prefixed),
                page_number=page_number,
            ))

    return chunks


def _build_page_offsets(document: ExtractedDocument) -> list[tuple[int, int]]:
    """Returns [(start_char_offset, page_number), ...] matching how
    ExtractedDocument.markdown was joined ("\\n\\n".join(page markdowns))."""

    offsets: list[tuple[int, int]] = []
    cursor = 0
    for page in document.pages:
        if not page.markdown.strip():
            continue
        offsets.append((cursor, page.page_number))
        cursor += len(page.markdown) + 2  # + "\n\n" separator

    return offsets


def _locate_page(full_markdown: str, section_content: str, page_offsets: list[tuple[int, int]]) -> Optional[int]:
    if not page_offsets:
        return None

    idx = full_markdown.find(section_content[:200])
    if idx == -1:
        return None

    page_number = page_offsets[0][1]
    for offset, number in page_offsets:
        if offset <= idx:
            page_number = number
        else:
            break
    return page_number
