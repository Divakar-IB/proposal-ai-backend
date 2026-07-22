from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import get_proposal_by_id, update_proposal
from database.db_enum import ProposalStatus
from database.models import Proposal
from generation.markdown_sections import assemble_markdown
from rendering.renderer import render_docx, render_pdf
from rendering.templates import get_template
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


async def render_proposal_document(
    db: AsyncSession, proposal_id: int, template_id: int, export_format: ExportFormat
) -> tuple[Proposal, bytes, str, str]:
    """Renders the proposal's stored proposal_json (the frozen, approved
    snapshot — never the live/mutable section rows) through the selected
    template. Returns (proposal, file_bytes, filename, content_type) so both
    the direct-download and email flows can share this single code path."""

    proposal = _proposal_or_404(await get_proposal_by_id(db, proposal_id))

    if not proposal.is_approved or not proposal.proposal_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal must be approved before it can be exported",
        )

    template = get_template(template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")

    markdown = assemble_markdown(
        proposal.proposal_json.get("title", proposal.title),
        proposal.proposal_json.get("sections", []),
    )

    try:
        if export_format == ExportFormat.PDF:
            content = render_pdf(markdown, template)
        else:
            content = render_docx(markdown, template)
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


async def export_and_email_proposal(
    db: AsyncSession, proposal_id: int, template_id: int, export_format: ExportFormat, email: str
) -> Proposal:
    proposal, content, filename, content_type = await render_proposal_document(
        db, proposal_id, template_id, export_format
    )

    try:
        await send_proposal_export_email(
            email, proposal.title, EmailAttachment(content, filename, content_type)
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to send proposal export email"
        )

    return proposal
