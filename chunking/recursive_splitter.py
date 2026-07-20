import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from chunking.tokenization import count_tokens

# 500 tokens / ~10% overlap: small enough for focused retrieval matches,
# large enough to keep coherent context for both embedding and drafting.
DEFAULT_CHUNK_SIZE_TOKENS = 500
DEFAULT_CHUNK_OVERLAP_TOKENS = 50

# A GFM table row ("| a | b |") and its header separator ("|---|---|" / "| :-- | --: |").
_TABLE_ROW_PATTERN = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_PATTERN = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def split_oversized_section(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE_TOKENS,
                             chunk_overlap: int = DEFAULT_CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Sub-splits a single heading-hierarchy section that exceeds chunk_size tokens.
    Returns [text] unchanged if it already fits. Markdown tables are split
    row-wise with the header/separator row repeated in every resulting piece —
    the generic recursive splitter alone can sever a table's header from its
    body rows once it falls back to newline-splitting an oversized section."""

    if count_tokens(text) <= chunk_size:
        return [text]

    pieces: list[str] = []
    for segment, is_table in _split_table_segments(text):
        if not segment.strip():
            continue
        if count_tokens(segment) <= chunk_size:
            pieces.append(segment.strip())
        elif is_table:
            pieces.extend(_split_table_rows(segment, chunk_size))
        else:
            pieces.extend(_split_prose(segment, chunk_size, chunk_overlap))

    return pieces


def _split_prose(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
    return [chunk.strip() for chunk in splitter.split_text(text) if chunk.strip()]


def _split_table_segments(text: str) -> list[tuple[str, bool]]:
    """Splits text into ordered (segment, is_table) pairs. A "table" segment
    starts at a header row immediately followed by a "|---|---|"-style
    separator row (so prose that merely contains a pipe character isn't
    mistaken for a table) and continues while subsequent lines keep matching
    the table-row shape."""

    lines = text.split("\n")
    segments: list[tuple[str, bool]] = []
    current: list[str] = []
    current_is_table = False

    for i, line in enumerate(lines):
        looks_like_table_start = (
            i + 1 < len(lines)
            and _TABLE_ROW_PATTERN.match(line)
            and _TABLE_SEPARATOR_PATTERN.match(lines[i + 1])
        )
        in_table_body = current_is_table and _TABLE_ROW_PATTERN.match(line)
        is_table_line = bool(looks_like_table_start or in_table_body)

        if current and is_table_line != current_is_table:
            segments.append(("\n".join(current), current_is_table))
            current = []

        current.append(line)
        current_is_table = is_table_line

    if current:
        segments.append(("\n".join(current), current_is_table))

    return segments


def _split_table_rows(table_text: str, chunk_size: int) -> list[str]:
    """Splits a Markdown table's data rows into token-bounded groups, each
    prefixed with the original header + separator row so every group renders
    as a valid, self-contained table on its own."""

    lines = [line for line in table_text.split("\n") if line.strip()]
    if len(lines) < 3:
        return [table_text.strip()]  # not enough structure to safely split by row

    header, separator, *body_rows = lines
    header_block = f"{header}\n{separator}"
    header_tokens = count_tokens(header_block)

    groups: list[str] = []
    current_rows: list[str] = []
    current_tokens = header_tokens

    for row in body_rows:
        row_tokens = count_tokens(row)
        if current_rows and current_tokens + row_tokens > chunk_size:
            groups.append("\n".join([header_block, *current_rows]))
            current_rows = []
            current_tokens = header_tokens
        current_rows.append(row)
        current_tokens += row_tokens

    if current_rows:
        groups.append("\n".join([header_block, *current_rows]))

    return groups or [table_text.strip()]
