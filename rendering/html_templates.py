from pathlib import Path
from typing import Optional

_HTML_DIR = Path(__file__).resolve().parent.parent / "html"

# template_id -> filename under html/. Add one entry here for every new
# visual template dropped into that folder — the id is what callers pass as
# ProposalExportRequest.template_id.
#
# Keep the ids/names in step with constants.EXPORT_TEMPLATES (which drives
# GET /proposals/templates and its S3 preview thumbnails) — nothing enforces
# that the two stay in sync, and they previously disagreed: id 1 was listed as
# "Modern" but rendered template_1.html, so picking Modern exported a design
# that didn't match its own preview.
DEFAULT_TEMPLATE_ID = 1

HTML_TEMPLATES: dict[int, str] = {
    1: "template_1.html",          # Professional (default)
    2: "minimal.html",             # Minimal
    3: "corporate_preview.html",   # Corporate
    4: "executive_preview.html",   # Executive
    5: "modern_preview.html",      # Modern
}


# template_id -> reference .docx supplying the Word styles Pandoc should use
# for that template's DOCX export (see rendering/renderer.py). Pandoc ignores
# the HTML's CSS, so without an entry here a template's DOCX comes out in
# Word's plain defaults and looks nothing like its PDF. Generate/refresh these
# with rendering/assets/docx_templates/generate_reference_docs.py.
_DOCX_REFERENCE_DIR = Path(__file__).resolve().parent / "assets" / "docx_templates"

DOCX_REFERENCES: dict[int, str] = {
    1: "professional.docx",
}


def get_html_template_path(template_id: int) -> Optional[Path]:
    filename = HTML_TEMPLATES.get(template_id)
    if filename is None:
        return None
    return _HTML_DIR / filename


def get_docx_reference_path(template_id: int) -> Optional[Path]:
    """None means "no styled reference for this template" — Pandoc then falls
    back to its own default styling for the DOCX export."""

    filename = DOCX_REFERENCES.get(template_id)
    if filename is None:
        return None
    path = _DOCX_REFERENCE_DIR / filename
    return path if path.is_file() else None
