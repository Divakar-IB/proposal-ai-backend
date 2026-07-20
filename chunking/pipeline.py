import dataclasses
import re
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

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
# A line that is only a page number ("Page 12", "12 of 45", "- 12 -") — a
# common scan/OCR artifact that adds no retrieval value and would otherwise
# get embedded as if it were content.
_PAGE_NUMBER_LINE = re.compile(r"^\s*(page\s+)?-?\s*\d{1,4}\s*(of\s+\d{1,4})?\s*-?\s*$", re.IGNORECASE)


def chunk_document(
    document: ExtractedDocument,
    root_prefix: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS,
) -> list[Chunk]:
    """clean -> header-split -> sub-split oversized sections -> breadcrumb-prefix -> Chunk objects.

    root_prefix (e.g. "Category > Document Title") is prepended to every
    breadcrumb so retrieval/citations carry full context, not just in-document headings.
    """

    document = _clean_document(document)
    page_lookup = {page.page_number: page for page in document.pages}
    page_offsets = _build_page_offsets(document)
    sections = split_by_headers(document.markdown)

    chunks: list[Chunk] = []
    for section_content, heading_breadcrumb in sections:
        full_breadcrumb = " > ".join(part for part in (root_prefix, heading_breadcrumb) if part)
        page_number = _locate_page(document.markdown, section_content, page_offsets)
        source_page = page_lookup.get(page_number) if page_number is not None else None

        for piece in split_oversized_section(section_content, chunk_size, chunk_overlap):
            prefixed = f"{full_breadcrumb}: {piece}" if full_breadcrumb else piece
            chunks.append(Chunk(
                content=prefixed,
                breadcrumb=full_breadcrumb,
                chunk_index=len(chunks),
                token_count=count_tokens(prefixed),
                page_number=page_number,
                confidence=source_page.ocr_confidence if source_page else None,
                source_type=source_page.extraction_method.value if source_page else None,
            ))

    return chunks


# ------------------------------------------------------------------
# Markdown cleaning — applied per page, before offsets are computed, so the
# character-offset math in _build_page_offsets/_locate_page stays consistent
# with whatever text was actually split. Deliberately conservative: strips
# clear scan/OCR noise only, never rewrites real content (headings/tables/
# lists are left untouched here — that's the chunkers' job).
# ------------------------------------------------------------------

def _clean_document(document: ExtractedDocument) -> ExtractedDocument:
    cleaned_pages = [
        dataclasses.replace(page, markdown=_clean_markdown_text(page.markdown))
        for page in document.pages
    ]
    joined = (
        "\n\n".join(page.markdown for page in cleaned_pages if page.markdown.strip())
        if cleaned_pages
        else _clean_markdown_text(document.markdown)
    )
    return dataclasses.replace(document, markdown=joined, pages=cleaned_pages)


def _clean_markdown_text(text: str) -> str:
    text = _CONTROL_CHARS.sub("", text)
    lines = [line.rstrip() for line in text.split("\n") if not _PAGE_NUMBER_LINE.match(line)]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


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
