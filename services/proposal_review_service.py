import json
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    build_proposals_query,
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
from generation.nodes import decide_section_status, draft_one_section, retrieve_chunks_for_section, run_quality_check
from generation.requirement_context import build_combined_requirements_json
from generation.sections import SECTION_DEFINITIONS, build_outline_instruction
from schemas.proposal import SectionEditItem
from utilities.logger import get_logger
from utilities.pagination import paginate

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
        "drafting_note": build_outline_instruction(definition.get("outline")) or None,
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


_PROPOSAL_STATUS_ORDER = {
    ProposalStatus.INPROGRESS: 0,
    ProposalStatus.GENERATING: 1,
    ProposalStatus.REVIEW: 2,
    ProposalStatus.DONE: 3,
}


async def set_proposal_status(db: AsyncSession, proposal_id: int, new_status: ProposalStatus) -> Proposal:
    """Manual status override for the proposal-tracking lifecycle (mainly
    used to mark a proposal DONE once review is finished). FAILED can always
    be set — it's an error/abort marker, not a pipeline stage. Otherwise the
    status can only move forward (inprogress -> generating -> review -> done);
    moving backward is rejected so a stale client call can't undo progress
    the pipeline has already made."""

    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    if new_status != ProposalStatus.FAILED and proposal.status != ProposalStatus.FAILED:
        current_rank = _PROPOSAL_STATUS_ORDER.get(proposal.status)
        new_rank = _PROPOSAL_STATUS_ORDER.get(new_status)
        if current_rank is not None and new_rank is not None and new_rank < current_rank:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot move proposal status backward from '{proposal.status.value}' to '{new_status.value}'",
            )

    logger.info(
        "proposal status changed | proposal_id=%s from=%s to=%s",
        proposal_id, proposal.status.value, new_status.value,
    )
    return await update_proposal(db, proposal, status=new_status)


async def list_proposals(
    db: AsyncSession,
    *,
    search: Optional[str] = None,
    proposal_status: Optional[ProposalStatus] = None,
    created_by: Optional[int] = None,
    created_from: Optional[datetime] = None,
    created_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 10,
) -> dict:
    """Search/filter/paginate proposals for the listing view, newest first.
    Reuses the same query-builder + paginate() pattern already used by the
    knowledge document listing endpoint (GET /document/list) — see
    database.crud.build_proposals_query and utilities.pagination.paginate.
    Returned "data" entries are Proposal ORM objects; the router maps them
    to ProposalResponse, same as every other endpoint in this file."""

    query = build_proposals_query(
        search=search,
        proposal_status=proposal_status,
        created_by=created_by,
        created_from=created_from,
        created_to=created_to,
    )
    return await paginate(db, query, page=page, limit=limit)
