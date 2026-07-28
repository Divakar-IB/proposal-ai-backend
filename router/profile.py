from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import get_current_user
from database.crud import get_user_by_id, update_user
from database.database import get_db
from schemas.profile import ProfileResponse, UpdateProfileRequest

router = APIRouter(
    prefix="/profile",
    tags=["Profile"],
)


async def _get_current_user_row(db: AsyncSession, current_user: dict):
    user = await get_user_by_id(db, current_user["user_id"])
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    user = await _get_current_user_row(db, current_user)
    return ProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        designation=user.designation,
        role=user.role,
    )


@router.put("", response_model=ProfileResponse)
async def update_profile(
    request: UpdateProfileRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Email is deliberately not accepted here — it's the login id and stays
    read-only. Password changes go through the existing /auth/reset_password
    endpoint, not this one. A field omitted from the body leaves its stored
    value untouched; a field included as null/empty clears it — same
    partial-update semantics as PUT /organization-settings."""

    user = await _get_current_user_row(db, current_user)
    fields = request.model_dump(exclude_unset=True)
    user = await update_user(db, user, **fields)

    return ProfileResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        designation=user.designation,
        role=user.role,
    )
