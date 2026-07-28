from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import require_role
from database.database import get_db
from database.db_enum import UserRole
from database.models import User
from schemas.team import (
    InviteTeamMemberRequest,
    InviteTeamMemberResponse,
    TeamMemberListResponse,
    TeamMemberResponse,
)
from services import team_service

router = APIRouter(
    prefix="/team",
    tags=["Team Management"],
)


def _to_response(user: User) -> TeamMemberResponse:
    return TeamMemberResponse(
        id=user.id,
        name=None,
        email=user.email,
        role=user.role,
        status="active" if user.is_active else "inactive",
        created_at=user.created_at,
    )


@router.post("/invite", response_model=InviteTeamMemberResponse)
async def invite_team_member(
    request: InviteTeamMemberRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    user = await team_service.invite_team_member(db, request)
    return InviteTeamMemberResponse(
        message="Invitation sent successfully.",
        email=user.email,
        role=user.role,
    )


@router.get("/members", response_model=TeamMemberListResponse)
async def list_team_members(
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    """Feature 5 (resend invite / activate / deactivate / delete / update
    role) can each be added here later as their own small endpoint, taking a
    user_id path param and reusing get_user_by_id — nothing about this
    listing endpoint needs to change to support them."""

    result = await team_service.list_team_members(db, page=page, limit=limit)
    if not result["data"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No data available")

    result["data"] = [_to_response(user) for user in result["data"]]
    return result
