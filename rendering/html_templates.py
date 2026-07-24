from pathlib import Path
from typing import Optional

_HTML_DIR = Path(__file__).resolve().parent.parent / "html"

# template_id -> filename under html/. Add one entry here for every new
# visual template dropped into that folder — the id is what callers pass as
# ProposalExportRequest.template_id.
HTML_TEMPLATES: dict[int, str] = {
    1: "template_1.html",
    2: "minimal.html",
    3: "corporate_preview.html",
    4: "executive_preview.html",
}


def get_html_template_path(template_id: int) -> Optional[Path]:
    filename = HTML_TEMPLATES.get(template_id)
    if filename is None:
        return None
    return _HTML_DIR / filename
