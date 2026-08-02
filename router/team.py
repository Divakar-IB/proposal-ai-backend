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
    UpdateTeamMemberRoleRequest,
    UpdateTeamMemberRoleResponse,
    UpdateTeamMemberStatusRequest,
    UpdateTeamMemberStatusResponse,
)
from services import team_service

router = APIRouter(
    prefix="/team",
    tags=["Team Management"],
)


def _to_response(user: User) -> TeamMemberResponse:
    return TeamMemberResponse(
        id=user.id,
        name=user.full_name,
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


@router.patch("/members/{user_id}/role", response_model=UpdateTeamMemberRoleResponse)
async def update_team_member_role(
    user_id: int,
    request: UpdateTeamMemberRoleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    user = await team_service.update_team_member_role(
        db,
        user_id=user_id,
        new_role=request.role,
        current_user_id=current_user.get("user_id"),
    )
    return UpdateTeamMemberRoleResponse(
        message="Role updated successfully.",
        id=user.id,
        email=user.email,
        role=user.role,
    )


@router.patch("/members/{user_id}/status", response_model=UpdateTeamMemberStatusResponse)
async def update_team_member_status(
    user_id: int,
    request: UpdateTeamMemberStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    """Activates or deactivates a member without removing them.

    A deactivated member keeps their account, proposals and documents and
    still appears in GET /team/members with `status: "inactive"` — they just
    cannot log in (login returns 403 for an inactive account). Send
    `is_active: true` to restore access.

    Deactivating is subject to the same guards as deletion: you cannot
    deactivate your own account or the last remaining admin. The call is
    idempotent — setting the state a member is already in is a no-op.
    """

    user = await team_service.set_team_member_active(
        db,
        user_id=user_id,
        is_active=request.is_active,
        current_user_id=current_user.get("user_id"),
    )
    return UpdateTeamMemberStatusResponse(
        message=f"Member {'activated' if user.is_active else 'deactivated'} successfully.",
        id=user.id,
        email=user.email,
        status="active" if user.is_active else "inactive",
    )


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_member(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role(UserRole.ADMIN)),
):
    """Soft-deletes the member (is_active = False) — the same effect as
    PATCH /members/{id}/status with `is_active: false`, kept as a separate
    verb for clients that model removal and deactivation differently.

    Their proposals and uploaded documents are left intact; that content
    belongs to the organisation. The member stops being able to log in but
    still appears in GET /team/members as `inactive`, and can be restored via
    the status endpoint. Refuses to remove your own account or the last
    remaining admin."""

    await team_service.delete_team_member(db, user_id=user_id, current_user_id=current_user.get("user_id"))
