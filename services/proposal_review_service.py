from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    build_proposals_query,
    get_proposal_by_id,
    get_proposal_status_counts,
    update_proposal,
)
from database.crud import (
    delete_proposal as delete_proposal_row,
)
from database.db_enum import ProposalStatus
from database.models import Proposal
from utilities.logger import get_logger
from utilities.pagination import paginate

logger = get_logger(__name__)


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
        proposal_id,
        proposal.status.value,
        new_status.value,
    )
    return await update_proposal(db, proposal, status=new_status)


async def delete_proposal(db: AsyncSession, proposal_id: int) -> None:
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    await delete_proposal_row(db, proposal)
    logger.info("proposal deleted | proposal_id=%s", proposal_id)


async def list_proposals(
    db: AsyncSession,
    *,
    search: str | None = None,
    proposal_status: ProposalStatus | None = None,
    created_by: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
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


async def get_proposal_stats(db: AsyncSession, *, created_by: int | None = None) -> dict:
    """Dashboard counts: total active proposals plus one flat field per
    status. Statuses with no proposals still come back as 0 rather than
    being omitted, so callers don't need to guard against missing keys."""

    counts = await get_proposal_status_counts(db, created_by=created_by)
    stats = {proposal_status.value: counts.get(proposal_status, 0) for proposal_status in ProposalStatus}
    stats["total"] = sum(stats.values())
    return stats
