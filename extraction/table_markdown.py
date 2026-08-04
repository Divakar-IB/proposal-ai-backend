"""Shared Markdown-table renderer for the extractors.

Both PDFExtractor (via PyMuPDF's table finder) and DocxExtractor produce a
grid of cell strings; this turns that grid into a Markdown pipe table. Keeping
it in one place matters because the chunker recognises tables by their pipe
syntax (see chunking/table_aware.py) — a malformed row silently stops being
treated as a table and gets split like prose.
"""

from typing import Any, Iterable, Optional

# A cell that still contains a newline or an unescaped pipe would terminate the
# row early and corrupt every column after it, so both are neutralised.
_CELL_BREAKS = ("\r\n", "\r", "\n")


def clean_cell(value: Any) -> str:
    """Flattens one cell to a single Markdown-safe line."""

    if value is None:
        return ""
    text = str(value)
    for token in _CELL_BREAKS:
        text = text.replace(token, " ")
    # Escape pipes so they stay content instead of becoming column separators.
    text = text.replace("|", "\\|")
    return " ".join(text.split())


def rows_to_markdown(rows: Iterable[Iterable[Any]], min_rows: int = 1) -> Optional[str]:
    """Renders a grid as a Markdown table, or returns None if there's nothing
    worth emitting.

    The first non-empty row becomes the header. Ragged rows are padded to the
    widest row rather than dropped — a table whose body has more columns than
    its header still renders, which matters for PDFs where the detected header
    row is often the sparsest.
    """

    cleaned = [[clean_cell(cell) for cell in row] for row in rows]
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if len(cleaned) < min_rows or not cleaned:
        return None

    width = max(len(row) for row in cleaned)
    if width == 0:
        return None
    padded = [row + [""] * (width - len(row)) for row in cleaned]

    header, *body = padded
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)
