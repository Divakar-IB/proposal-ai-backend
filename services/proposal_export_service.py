import os
import tempfile

import pypandoc
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from database.crud import get_proposal_by_id, update_proposal
from database.db_enum import ProposalStatus
from database.models import Proposal
from generation.markdown_sections import assemble_markdown
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

_EXPORTABLE_STATUSES = {ProposalStatus.APPROVED, ProposalStatus.DONE}


def build_canonical_markdown(proposal: Proposal) -> str:
    """The stored per-section Markdown, in order, is the canonical source —
    export always rebuilds from this rather than any previously generated
    file, so a later section edit is reflected in the next export without
    regenerating anything through the LLM."""

    sections = [
        {"title": section.title, "content": section.content, "order_index": section.order_index}
        for section in proposal.sections
    ]
    return assemble_markdown(proposal.title, sections)


def _markdown_to_docx_bytes(markdown: str) -> bytes:
    fd, tmp_path = tempfile.mkstemp(suffix=".docx")
    os.close(fd)
    try:
        pypandoc.convert_text(markdown, "docx", format="md", outputfile=tmp_path)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        os.unlink(tmp_path)


def _markdown_to_pdf_bytes(markdown: str) -> bytes:
    html = pypandoc.convert_text(markdown, "html", format="md")
    return HTML(string=html).write_pdf()


async def export_proposal(db: AsyncSession, proposal_id: int) -> Proposal:
    """Renders the proposal's canonical Markdown to DOCX (pypandoc) and PDF
    (pypandoc -> HTML -> weasyprint), uploads both to S3, and records their
    paths. Only allowed once the proposal has been explicitly approved —
    export is never a substitute for that review step."""

    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    if proposal.status not in _EXPORTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Proposal must be approved before it can be exported",
        )

    markdown = build_canonical_markdown(proposal)

    try:
        docx_bytes = _markdown_to_docx_bytes(markdown)
        pdf_bytes = _markdown_to_pdf_bytes(markdown)
    except Exception:
        logger.exception("proposal export rendering failed | proposal_id=%s", proposal_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to render proposal export"
        )

    docx_key = S3PathBuilder.proposal_docx(user_id=proposal.user_id, proposal_id=proposal.id)
    pdf_key = S3PathBuilder.proposal_pdf(user_id=proposal.user_id, proposal_id=proposal.id)

    s3_service.upload_bytes(
        docx_bytes, docx_key, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    s3_service.upload_bytes(pdf_bytes, pdf_key, content_type="application/pdf")

    logger.info("proposal exported | proposal_id=%s docx_key=%s pdf_key=%s", proposal_id, docx_key, pdf_key)

    return await update_proposal(
        db, proposal,
        docx_path=docx_key,
        pdf_path=pdf_key,
        status=ProposalStatus.DONE,
    )
