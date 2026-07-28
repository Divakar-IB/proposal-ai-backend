from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import hash_password
from database.crud import build_users_query, create_user, get_user_by_email
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
