from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import (
    create_proposal,
    get_proposal_by_id,
    get_requirement_document_by_id,
)
from database.database import get_db
from database.db_enum import ProposalStatus
from database.models import Proposal
from schemas.proposal import ProposalGenerateRequest, ProposalResponse
from tasks.arq_pool import get_arq_pool
from utilities.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(
    prefix="/proposals",
    tags=["Proposals"],
)


@router.post("/generate", response_model=ProposalResponse, status_code=status.HTTP_202_ACCEPTED)
async def generate_proposal_endpoint(
    request: ProposalGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    requirement_document = await get_requirement_document_by_id(db, request.requirement_document_id)
    if requirement_document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requirement document not found")

    proposal = Proposal(
        requirement_document_id=request.requirement_document_id,
        user_id=user_id,
        title=f"Proposal — {requirement_document.file_name}",
        status=ProposalStatus.GENERATING,
    )
    proposal = await create_proposal(db, proposal)
    logger.info("proposal created | proposal_id=%s requirement_document_id=%s", proposal.id, request.requirement_document_id)

    pool = await get_arq_pool()
    await pool.enqueue_job(
        "proposal_generation_job",
        request.requirement_document_id,
        proposal.id,
        user_id,
        request.category_ids,
    )

    return proposal


@router.get("/{proposal_id}", response_model=ProposalResponse)
async def get_proposal(
    proposal_id: int,
    db: AsyncSession = Depends(get_db),
):
    proposal = await get_proposal_by_id(db, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")
    return proposal
