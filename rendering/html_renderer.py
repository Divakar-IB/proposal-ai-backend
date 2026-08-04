from datetime import datetime

import pypandoc
from jinja2 import Environment, FileSystemLoader

from rendering.html_templates import get_html_template_path

DEFAULT_PROPOSAL_VERSION = "v1"


def _section_to_html(section: dict) -> str:
    """A section's content is stored as Markdown (it may itself contain
    "### " subsection headings from generation/sections.py's outline
    instruction) — convert it to an HTML fragment so the Jinja template only
    ever has to drop in final markup, never re-implement a Markdown
    renderer."""

    return pypandoc.convert_text(section.get("content") or "", "html", format="md")


def render_proposal_html(
    proposal_json: dict,
    template_id: int,
    client_name: str,
    proposal_id: int,
    organization_name: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
    version: str = DEFAULT_PROPOSAL_VERSION,
) -> str:
    """JSON -> HTML: renders the selected html/template_N.html file with the
    proposal's title, client, reference, and sections. Each section's
    Markdown content is pre-converted to HTML before being handed to the
    template.

    The organization_* / contact_* values come from the single
    OrganizationSettings row (see services/proposal_export_service.py) and
    populate the cover page. Every one of them is optional on that model, so
    templates must tolerate None — they fall back to a placeholder rather
    than printing "None" into a client-facing document."""

    template_path = get_html_template_path(template_id)
    if template_path is None or not template_path.is_file():
        raise FileNotFoundError(f"No HTML template registered for template_id={template_id}")

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)

    sections = [
        {"title": section.get("title", ""), "content_html": _section_to_html(section)}
        for section in proposal_json.get("sections", [])
    ]

    return template.render(
        proposal_title=proposal_json.get("title", ""),
        client_name=client_name,
        reference=f"PROP-{proposal_id}",
        generated_date=datetime.now().strftime("%d %B %Y"),
        organization_name=organization_name or None,
        contact_name=contact_name or None,
        contact_email=contact_email or None,
        version=version or DEFAULT_PROPOSAL_VERSION,
        sections=sections,
    )
