import os
import tempfile

import pypandoc
from weasyprint import HTML


def render_pdf_from_html(html: str) -> bytes:
    """HTML -> PDF via WeasyPrint. The template's own <style> block (already
    embedded in the rendered HTML) drives all visual styling — no separate
    CSS is injected here."""

    return HTML(string=html).write_pdf()


def render_docx_from_html(html: str) -> bytes:
    """HTML -> DOCX via Pandoc. Pandoc's HTML reader only maps a subset of
    CSS onto Word styles (headings, bold/italic, tables, lists) — a
    template's finer visual details (custom fonts, box-shadows, etc.) won't
    carry over, so DOCX output looks plainer than the PDF for the same
    template."""

    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        pypandoc.convert_text(html, "docx", format="html", outputfile=tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
