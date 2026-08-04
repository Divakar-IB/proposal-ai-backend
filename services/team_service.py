from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import hash_password
from database.crud import (
    build_users_query,
    create_user,
    delete_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
)
from database.db_enum import UserRole
from database.models import User
from schemas.team import InviteTeamMemberRequest
from utilities.email_service import send_team_invite_email
from utilities.generic import generate_temp_password
from utilities.logger import get_logger
from utilities.pagination import paginate

logger = get_logger(__name__)


async def invite_team_member(db: AsyncSession, request: InviteTeamMemberRequest) -> User:
    """Reuses the same existence-check + hash + create_user primitives as
    create_user_by_admin (authentication/auth_service.py) — the invite flow
    differs only in where the password comes from (generated here instead of
    admin-supplied) and in emailing it afterward, so it's a sibling of that
    flow rather than a duplicate of its logic."""

    if await get_user_by_email(db, request.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    temporary_password = generate_temp_password()

    user = User(
        email=request.email,
        hashed_password=hash_password(temporary_password),
        role=request.role,
        is_first_login=True,
    )
    user = await create_user(db, user)

    try:
        await send_team_invite_email(user.email, temporary_password)
    except Exception:
        logger.exception("failed to send team invite email | user_id=%s email=%s", user.id, user.email)
        # The account already exists at this point — surface a distinct
        # error so the admin knows the invite needs resending (Feature 5),
        # rather than retrying this call and hitting the 409 above.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="User created, but the invitation email failed to send.",
        )

    logger.info("team member invited | user_id=%s email=%s role=%s", user.id, user.email, user.role)
    return user


async def list_team_members(db: AsyncSession, *, page: int = 1, limit: int = 10) -> dict:
    query = build_users_query()
    return await paginate(db, query, page=page, limit=limit)


async def update_team_member_role(db: AsyncSession, *, user_id: int, new_role: UserRole, current_user_id: int) -> User:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    if user.id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own role",
        )

    if user.role == UserRole.ADMIN and new_role != UserRole.ADMIN:
        admin_count = await db.scalar(
            select(func.count()).select_from(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        )
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin",
            )

    user = await update_user(db, user, role=new_role)
    logger.info("team member role updated | user_id=%s email=%s role=%s", user.id, user.email, user.role)
    return user


async def _assert_removable(db: AsyncSession, user: User, current_user_id: int, action: str) -> None:
    """Shared guards for deactivating or deleting a member: an admin must not
    lock themselves out, and the organisation must not be left without an
    admin who can administer it."""

    if user.id == current_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"You cannot {action} your own account",
        )

    if user.role == UserRole.ADMIN:
        admin_count = await db.scalar(
            select(func.count()).select_from(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True))
        )
        if admin_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the last admin",
            )


async def set_team_member_active(db: AsyncSession, *, user_id: int, is_active: bool, current_user_id: int) -> User:
    """Activates or deactivates a member.

    Deactivating is the same state change as deleting (both set is_active =
    False) — the difference is intent, not effect. A deactivated member keeps
    their account and content and is still listed, but cannot log in: the
    login path rejects an inactive user with a 403 (see
    authentication/auth_service.login).
    """

    user = await get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    if user.is_active == is_active:
        return user  # already in the requested state — nothing to do

    if not is_active:
        await _assert_removable(db, user, current_user_id, action="deactivate")

    user = await update_user(db, user, is_active=is_active)
    logger.info(
        "team member %s | user_id=%s email=%s",
        "activated" if is_active else "deactivated",
        user.id,
        user.email,
    )
    return user


async def delete_team_member(db: AsyncSession, *, user_id: int, current_user_id: int) -> None:
    """Soft-deletes the member (is_active = False), the same pattern used for
    every other resource in this codebase. Their proposals and uploaded
    documents are deliberately left intact — that content belongs to the
    organisation, not to the person who happened to upload it.

    Note this leaves the row (and therefore the email address, which is
    UNIQUE) in place, so the same address cannot be re-invited afterwards;
    reactivate the member via PATCH /team/members/{id}/status instead.
    """

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found")

    await _assert_removable(db, user, current_user_id, action="delete")

    await delete_user(db, user)
    logger.info("team member deleted | user_id=%s email=%s", user.id, user.email)
