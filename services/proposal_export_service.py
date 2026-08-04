from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_organization_settings, get_proposal_by_id, update_proposal
from database.db_enum import ProposalStatus
from database.models import Proposal
from generation.markdown_sections import assemble_markdown, markdown_to_json
from rendering.html_renderer import render_proposal_html
from rendering.html_templates import get_docx_reference_path, get_html_template_path
from rendering.renderer import render_docx_from_html, render_pdf_from_html
from schemas.proposal import ExportFormat
from utilities.email_service import EmailAttachment, send_proposal_export_email
from utilities.generic import sanitize_filename
from utilities.logger import get_logger

logger = get_logger(__name__)

_CONTENT_TYPES = {
    ExportFormat.PDF: "application/pdf",
    ExportFormat.DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _proposal_or_404(proposal: Proposal | None) -> Proposal:
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal


def _build_proposal_json(proposal: Proposal) -> dict:
    """sections -> Markdown -> JSON — the same shape Proposal.proposal_json
    will eventually be frozen into at approval time. Building it live from
    the current section rows means export works before that approve flow is
    wired up; once it is, this can be swapped for reading the frozen
    snapshot (proposal.proposal_json) without touching anything downstream."""

    sections = [
        {"title": section.title, "content": section.content, "order_index": section.order_index}
        for section in proposal.sections
    ]
    markdown = assemble_markdown(proposal.title, sections)
    return markdown_to_json(markdown)


async def render_proposal_document(
    db: AsyncSession, proposal_id: int, template_id: int, export_format: ExportFormat
) -> tuple[Proposal, bytes, str, str]:
    """sections -> Markdown -> JSON -> HTML (the selected html/template_N.html
    Jinja template) -> PDF (WeasyPrint) or DOCX (Pandoc). Not gated on
    approval right now — that gate goes back in once the review/approve flow
    is wired up end-to-end; for now this always renders straight from the
    live section rows."""

    proposal = _proposal_or_404(await get_proposal_by_id(db, proposal_id))

    if not proposal.sections:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Proposal has no generated sections to export"
        )

    if get_html_template_path(template_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    # Cover-page details come from the single OrganizationSettings row; every
    # column on it is nullable and the row may not exist at all, so the
    # template falls back to placeholders rather than printing "None".
    settings = await get_organization_settings(db)

    proposal_json = _build_proposal_json(proposal)
    html = render_proposal_html(
        proposal_json,
        template_id,
        client_name=proposal.client_name,
        proposal_id=proposal.id,
        organization_name=settings.organization_name if settings else None,
        contact_name=settings.default_signee_name if settings else None,
        contact_email=settings.contact_email if settings else None,
    )

    try:
        content = (
            render_pdf_from_html(html)
            if export_format == ExportFormat.PDF
            else render_docx_from_html(html, reference_docx=get_docx_reference_path(template_id))
        )
    except Exception:
        logger.exception(
            "proposal export rendering failed | proposal_id=%s template_id=%s format=%s",
            proposal_id, template_id, export_format,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to render proposal export"
        )

    if proposal.status != ProposalStatus.DONE:
        proposal = await update_proposal(db, proposal, status=ProposalStatus.DONE)

    filename = sanitize_filename(f"{proposal.title}.{export_format.value}")
    logger.info(
        "proposal exported | proposal_id=%s template_id=%s format=%s",
        proposal_id, template_id, export_format,
    )
    return proposal, content, filename, _CONTENT_TYPES[export_format]


async def email_rendered_proposal(
    email: str, proposal: Proposal, content: bytes, filename: str, content_type: str
) -> None:
    """Emails an already-rendered export — kept separate from
    render_proposal_document so the caller can render once and both return
    the binary in the response *and* email it, instead of rendering twice."""

    try:
        await send_proposal_export_email(
            email, proposal.title, EmailAttachment(content, filename, content_type)
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send proposal export email"
        )
