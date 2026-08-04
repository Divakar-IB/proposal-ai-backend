"""Table-aware splitting for oversized sections.

The plain recursive splitter breaks on "\\n", which inside a Markdown table is
a *row* boundary. A table larger than one chunk therefore gets cut mid-table
and every continuation chunk arrives as unlabelled rows — the header naming
the columns only survives in the first one. Those chunks are then embedded and
later pasted verbatim into drafting prompts, where a run of bare numbers is
worse than useless.

This module splits a section into table and non-table segments so a table can
be divided on row boundaries with its header re-emitted at the top of every
piece, while prose keeps the existing recursive behaviour.
"""

import re
from collections.abc import Callable, Iterator

from chunking.tokenization import count_tokens

# A Markdown table row: starts and ends with a pipe. Escaped pipes inside cells
# (see extraction/table_markdown.py) do not terminate the row, so a simple
# anchor test is enough to classify the line.
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
# The "| --- | --- |" line directly under a header.
_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$")


def _is_table_row(line: str) -> bool:
    return bool(_TABLE_ROW.match(line))


def segment(text: str) -> Iterator[tuple[str, str]]:
    """Yields ("table" | "text", block) in document order.

    A run of consecutive pipe rows counts as a table only when it has at least
    a header plus one more row; a lone pipe line is far more likely to be prose
    containing a pipe than a real table.
    """

    lines = text.splitlines()
    buffer: list[str] = []
    kind = "text"

    def flush() -> Iterator[tuple[str, str]]:
        if not buffer:
            return
        block = "\n".join(buffer).strip("\n")
        if block.strip():
            yield kind, block

    for line in lines:
        line_kind = "table" if _is_table_row(line) else "text"
        if line_kind != kind:
            # A single pipe line on its own is not a table — reclassify it.
            if kind == "table" and len(buffer) < 2:
                kind = "text"
            else:
                yield from flush()
                buffer = []
                kind = line_kind
        buffer.append(line)

    if kind == "table" and len(buffer) < 2:
        kind = "text"
    yield from flush()


def split_table(table: str, chunk_size: int) -> list[str]:
    """Splits a Markdown table on row boundaries, repeating the header (and its
    separator) at the top of every piece so each chunk is self-describing."""

    lines = [line for line in table.splitlines() if line.strip()]
    if not lines:
        return []
    if count_tokens(table) <= chunk_size:
        return [table]

    header = lines[0]
    body_start = 1
    separator = ""
    if len(lines) > 1 and _TABLE_SEPARATOR.match(lines[1]):
        separator = lines[1]
        body_start = 2

    prefix = [header] + ([separator] if separator else [])
    prefix_tokens = count_tokens("\n".join(prefix))

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = prefix_tokens

    for row in lines[body_start:]:
        row_tokens = count_tokens(row)
        if current and current_tokens + row_tokens > chunk_size:
            pieces.append("\n".join(prefix + current))
            current = []
            current_tokens = prefix_tokens
        current.append(row)
        current_tokens += row_tokens

    if current:
        pieces.append("\n".join(prefix + current))
    return pieces


def pack(pieces: list[str], chunk_size: int) -> list[str]:
    """Greedily recombines adjacent pieces that still fit together, so a short
    paragraph followed by a small table does not become two tiny chunks."""

    packed: list[str] = []
    for piece in pieces:
        if not piece.strip():
            continue
        if packed:
            merged = f"{packed[-1]}\n\n{piece}"
            if count_tokens(merged) <= chunk_size:
                packed[-1] = merged
                continue
        packed.append(piece)
    return packed


def split_section(text: str, chunk_size: int, split_prose: Callable[[str], list[str]]) -> list[str]:
    """Splits one oversized section, keeping Markdown tables coherent.

    `split_prose` handles non-table runs (the existing recursive splitter), so
    prose chunking behaviour — including overlap — is unchanged.
    """

    pieces: list[str] = []
    for kind, block in segment(text):
        if kind == "table":
            pieces.extend(split_table(block, chunk_size))
        elif count_tokens(block) <= chunk_size:
            pieces.append(block)
        else:
            pieces.extend(split_prose(block))

    return pack(pieces, chunk_size)
