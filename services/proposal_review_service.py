import json

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    get_proposal_by_id,
    get_proposal_section_by_id,
    get_proposal_sections_by_ids,
    get_requirement_documents_by_proposal_id,
    has_any_knowledge_chunks,
    update_proposal,
    update_proposal_section,
)
from database.db_enum import ProposalSectionStatus, ProposalStatus
from database.models import Proposal, ProposalSection
from generation.markdown_sections import assemble_markdown, markdown_to_json
from generation.nodes import decide_section_status, draft_one_section, retrieve_chunks_for_section, run_quality_check
from generation.requirement_context import build_combined_requirements_json
from generation.sections import SECTION_DEFINITIONS
from schemas.proposal import SectionEditItem
from utilities.logger import get_logger

logger = get_logger(__name__)

_SECTION_DEFINITIONS_BY_KEY = {definition["key"]: definition for definition in SECTION_DEFINITIONS}


async def _get_section_or_404(db: AsyncSession, section_id: int) -> ProposalSection:
    section = await get_proposal_section_by_id(db, section_id)
    if section is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal section not found")
    return section


async def edit_sections(
    db: AsyncSession, proposal_id: int, edits: list[SectionEditItem]
) -> list[ProposalSection]:
    """Bulk version of a single-section content edit — user-edited content
    replaces the drafted content directly for every section in one request;
    status/review_flag are left untouched, approving is a separate explicit
    action. Every section_id must belong to proposal_id, and duplicates are
    rejected up front so partial writes can't happen."""

    section_ids = [edit.section_id for edit in edits]
    if len(section_ids) != len(set(section_ids)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Duplicate section_id in the edit list",
        )

    sections_by_id = {
        section.id: section for section in await get_proposal_sections_by_ids(db, section_ids)
    }
    missing = [section_id for section_id in section_ids if section_id not in sections_by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Proposal sections not found: {missing}"
        )

    foreign = [
        section_id for section_id, section in sections_by_id.items() if section.proposal_id != proposal_id
    ]
    if foreign:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Sections do not belong to proposal {proposal_id}: {foreign}",
        )

    updated = []
    for edit in edits:
        section = sections_by_id[edit.section_id]
        updated.append(await update_proposal_section(db, section, content=edit.content))
    return updated


async def approve_section(db: AsyncSession, section_id: int) -> ProposalSection:
    section = await _get_section_or_404(db, section_id)
    return await update_proposal_section(
        db, section,
        status=ProposalSectionStatus.APPROVED,
        review_flag=False,
    )


async def regenerate_section(db: AsyncSession, section_id: int) -> ProposalSection:
    """One fresh draft + quality-check pass for a single section, reusing the
    exact same per-section helpers the LangGraph pipeline uses (generation/nodes.py)
    so drafting/review logic is never duplicated between the automated pipeline
    and this user-triggered path. Unlike the automated pipeline, this never
    force-approves — it's a single explicit action with a predictable, bounded
    (one draft call + one review call) token cost per click."""

    section = await _get_section_or_404(db, section_id)

    proposal = await get_proposal_by_id(db, section.proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found for this section")

    requirement_documents = await get_requirement_documents_by_proposal_id(db, proposal.id)
    if not requirement_documents or not any(document.parsed_data for document in requirement_documents):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement documents have no extracted requirements to regenerate this section from",
        )

    definition = _SECTION_DEFINITIONS_BY_KEY.get(section.section_key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unknown section key '{section.section_key}' — no section definition to regenerate from",
        )

    requirements_json = build_combined_requirements_json(requirement_documents)
    requirements = json.loads(requirements_json)
    has_knowledge = await has_any_knowledge_chunks(db)

    section_state = {
        "key": definition["key"],
        "title": definition["title"],
        "query_fields": definition["query_fields"],
        "drafting_note": definition.get("drafting_note"),
        "retrieved_chunks": [],
        "content": None,
        "citations": [],
        "status": "pending",
        "retry_count": section.retry_count,
        "feedback": None,
        "confidence_score": None,
        "review_flag": False,
    }

    section_state["retrieved_chunks"] = await retrieve_chunks_for_section(
        section_state, requirements, proposal.category_ids, has_knowledge,
    )

    content, citations = draft_one_section(section_state, requirements_json)
    section_state["content"] = content
    section_state["citations"] = citations

    result = run_quality_check(section_state, requirements_json)
    # feedback is discarded here — it only exists to seed the *next* automated
    # draft attempt's prompt, and a single regenerate pass has no next attempt.
    new_status, _feedback, review_flag = decide_section_status(result, force_approve=False)
    logger.info(
        "section regenerated | section_id=%s status=%s review_flag=%s",
        section_id, new_status, review_flag,
    )

    return await update_proposal_section(
        db, section,
        content=content,
        citations=citations,
        status=ProposalSectionStatus(new_status),
        retry_count=section.retry_count + 1,
        confidence_score=result.confidence_score,
        review_flag=review_flag,
    )


_UNRESOLVED_SECTION_STATUSES = {
    ProposalSectionStatus.PENDING,
    ProposalSectionStatus.DRAFTING,
    ProposalSectionStatus.NEEDS_REVISION,
}


async def approve_proposal(db: AsyncSession, proposal_id: int) -> Proposal:
    """Whole-proposal sign-off: every section must already be drafted and
    clear of manual review before the proposal can move to APPROVED. The
    canonical Markdown — built from the sections exactly as they stand at
    this moment, including any manual edits made during review — is
    snapshotted onto Proposal.approved_markdown right here, so export
    always has a fixed, already-approved source to render from instead of
    re-reading mutable section rows. The same Markdown is also parsed into
    Proposal.proposal_json. Both snapshots (and is_approved) are refreshed
    on every call, including re-approval of an already-approved proposal,
    so they always reflect the latest edited content."""

    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    if not proposal.sections:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Proposal has no generated sections to approve"
        )

    unresolved = [
        section.id
        for section in proposal.sections
        if section.review_flag or section.status in _UNRESOLVED_SECTION_STATUSES
    ]
    if unresolved:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Sections still need review before the proposal can be approved: {unresolved}",
        )

    for section in proposal.sections:
        if section.status != ProposalSectionStatus.APPROVED:
            await update_proposal_section(db, section, status=ProposalSectionStatus.APPROVED)

    approved_markdown = assemble_markdown(proposal.title, [
        {"title": section.title, "content": section.content, "order_index": section.order_index}
        for section in proposal.sections
    ])
    proposal_json = markdown_to_json(approved_markdown)

    logger.info("proposal approved | proposal_id=%s", proposal_id)
    return await update_proposal(
        db, proposal,
        status=ProposalStatus.APPROVED,
        approved_markdown=approved_markdown,
        proposal_json=proposal_json,
        is_approved=True,
    )
