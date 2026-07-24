from datetime import datetime

import pypandoc
from jinja2 import Environment, FileSystemLoader

from rendering.html_templates import get_html_template_path


def _section_to_html(section: dict) -> str:
    """A section's content is stored as Markdown (it may itself contain
    "### " subsection headings from generation/sections.py's outline
    instruction) — convert it to an HTML fragment so the Jinja template only
    ever has to drop in final markup, never re-implement a Markdown
    renderer."""

    return pypandoc.convert_text(section.get("content") or "", "html", format="md")


def render_proposal_html(
    proposal_json: dict, template_id: int, client_name: str, proposal_id: int
) -> str:
    """JSON -> HTML: renders the selected html/template_N.html file with the
    proposal's title, client, reference, and sections. Each section's
    Markdown content is pre-converted to HTML before being handed to the
    template."""

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
        sections=sections,
    )
