from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import require_role
from database.crud import (
    create_organization_settings,
    get_organization_settings,
    update_organization_settings,
)
from database.database import get_db
from database.db_enum import UserRole
from database.models import OrganizationSettings
from schemas.organization_settings import (
    OrganizationSettingsResponse,
    OrganizationSettingsUpdateRequest,
)
from services import organization_settings_service
from utilities.s3_service import S3Service

router = APIRouter(
    prefix="/organization-settings",
    tags=["Organization Settings"],
)

s3_service = S3Service()


def _to_response(settings: OrganizationSettings | None) -> OrganizationSettingsResponse:
    if settings is None:
        return OrganizationSettingsResponse()

    return OrganizationSettingsResponse(
        id=settings.id,
        organization_name=settings.organization_name,
        contact_email=settings.contact_email,
        default_signee_name=settings.default_signee_name,
        default_signee_designation=settings.default_signee_designation,
        proposal_naming_template=settings.proposal_naming_template,
        logo_url=s3_service.generate_presigned_url(settings.logo_path) if settings.logo_path else None,
        created_at=settings.created_at,
        updated_at=settings.updated_at,
    )


@router.get("", response_model=OrganizationSettingsResponse)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    """No record yet? Return an all-empty response rather than a 404 — the
    Settings page always has something to render."""

    settings = await get_organization_settings(db)
    return _to_response(settings)


@router.put("", response_model=OrganizationSettingsResponse)
async def save_settings(
    request: OrganizationSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    """Create-or-update the single settings row. A field omitted from the
    request body leaves its stored value untouched; a field included as
    null/empty overwrites the stored value — so re-saving the form with a
    field cleared actually clears it instead of silently keeping the old
    value."""

    settings = await get_organization_settings(db)
    fields = request.model_dump(exclude_unset=True)

    if settings is None:
        settings = await create_organization_settings(db, OrganizationSettings(**fields))
    else:
        settings = await update_organization_settings(db, settings, **fields)

    return _to_response(settings)


@router.post("/logo", response_model=OrganizationSettingsResponse)
async def upload_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    """Dedicated logo upload flow — kept separate from `PUT /organization-
    settings` so uploading/replacing the logo never requires resending the
    rest of the form."""

    settings = await organization_settings_service.upload_logo(db, file)
    return _to_response(settings)


@router.delete("/logo", response_model=OrganizationSettingsResponse)
async def remove_logo(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    settings = await organization_settings_service.delete_logo(db)
    return _to_response(settings)
