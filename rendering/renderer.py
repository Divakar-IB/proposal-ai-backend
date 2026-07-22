import os
import tempfile

import pypandoc
from weasyprint import HTML

from rendering.templates import TemplateDefinition


def render_pdf(markdown: str, template: TemplateDefinition) -> bytes:
    """Markdown -> HTML (Pandoc) -> PDF (WeasyPrint), matching the pipeline
    services/proposal_export_service.py already used — the only new part is
    wrapping the HTML body in the selected template's CSS before handing it
    to WeasyPrint."""

    html_body = pypandoc.convert_text(markdown, "html", format="md")
    html = f"<html><head><meta charset='utf-8'><style>{template.pdf_css}</style></head><body>{html_body}</body></html>"
    return HTML(string=html).write_pdf()


def render_docx(markdown: str, template: TemplateDefinition) -> bytes:
    """Markdown -> DOCX (Pandoc), styled via the template's reference .docx —
    Pandoc reuses that file's Heading 1/Heading 2/Normal styles instead of its
    own defaults, so the same conversion call renders differently per
    template with no extra runtime rendering logic."""

    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        pypandoc.convert_text(
            markdown, "docx", format="md", outputfile=tmp_path,
            extra_args=[f"--reference-doc={template.docx_reference_path}"],
        )
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)
