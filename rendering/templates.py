from pathlib import Path

from pydantic import BaseModel

_ASSETS_DIR = Path(__file__).parent / "assets" / "docx_templates"


class TemplateDefinition(BaseModel):
    id: int
    name: str
    # Inline CSS wrapped around the Pandoc-rendered HTML before it's handed to
    # WeasyPrint — this is what makes the PDF for this template look distinct.
    pdf_css: str
    # Pandoc "--reference-doc" — a real .docx whose Heading 1/Heading 2/Normal
    # styles are reused for the generated document, giving the DOCX output the
    # same distinct look without hand-building the document with python-docx.
    docx_reference_path: Path


PROPOSAL_TEMPLATES: dict[int, TemplateDefinition] = {
    1: TemplateDefinition(
        id=1,
        name="Classic Serif",
        pdf_css="""
            body { font-family: Georgia, 'Times New Roman', serif; color: #1a1a1a; margin: 2.5cm; line-height: 1.5; }
            h1 { font-size: 26pt; color: #1f3864; border-bottom: 2px solid #1f3864; padding-bottom: 8px; }
            h2 { font-size: 16pt; color: #1f3864; margin-top: 28px; }
            p { font-size: 11pt; }
        """,
        docx_reference_path=_ASSETS_DIR / "classic_serif.docx",
    ),
    2: TemplateDefinition(
        id=2,
        name="Modern Blue",
        pdf_css="""
            body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #222222; margin: 2.2cm; line-height: 1.55; }
            h1 { font-size: 27pt; color: #0b5394; }
            h2 { font-size: 15pt; color: #0b5394; margin-top: 26px; border-left: 4px solid #0b5394; padding-left: 10px; }
            p { font-size: 10.5pt; }
        """,
        docx_reference_path=_ASSETS_DIR / "modern_blue.docx",
    ),
    3: TemplateDefinition(
        id=3,
        name="Minimal Mono",
        pdf_css="""
            body { font-family: Arial, sans-serif; color: #333333; margin: 3cm; line-height: 1.7; }
            h1 { font-size: 22pt; font-weight: 300; color: #333333; letter-spacing: 1px; }
            h2 { font-size: 13pt; font-weight: 600; color: #666666; margin-top: 32px; text-transform: uppercase; letter-spacing: 0.5px; }
            p { font-size: 10.5pt; }
        """,
        docx_reference_path=_ASSETS_DIR / "minimal_mono.docx",
    ),
    4: TemplateDefinition(
        id=4,
        name="Corporate Bold",
        pdf_css="""
            body { font-family: Arial, sans-serif; color: #1a1a1a; margin: 2cm; line-height: 1.5; }
            h1 { font-size: 30pt; font-weight: 800; color: #003366; border-bottom: 6px solid #003366; padding-bottom: 10px; }
            h2 { font-size: 16pt; font-weight: 700; color: #003366; margin-top: 26px; }
            p { font-size: 11pt; }
        """,
        docx_reference_path=_ASSETS_DIR / "corporate_bold.docx",
    ),
}


def get_template(template_id: int) -> TemplateDefinition | None:
    return PROPOSAL_TEMPLATES.get(template_id)
