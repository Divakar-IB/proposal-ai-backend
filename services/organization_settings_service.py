from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from database.crud import (
    create_organization_settings,
    get_organization_settings,
    update_organization_settings,
)
from database.models import OrganizationSettings
from utilities.logger import get_logger
from utilities.s3_service import S3PathBuilder, S3Service

logger = get_logger(__name__)
s3_service = S3Service()

ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg"}
ALLOWED_LOGO_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg"}
MAX_LOGO_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def _validate_logo(file: UploadFile) -> None:
    extension = Path(file.filename or "").suffix.lstrip(".").lower()
    if extension not in ALLOWED_LOGO_EXTENSIONS or file.content_type not in ALLOWED_LOGO_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Logo must be a PNG or JPEG image.",
        )
    if file.size is not None and file.size > MAX_LOGO_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Logo must be 2MB or smaller.",
        )


async def _get_or_create_settings(db: AsyncSession) -> OrganizationSettings:
    settings = await get_organization_settings(db)
    if settings is None:
        settings = await create_organization_settings(db, OrganizationSettings())
    return settings


async def upload_logo(db: AsyncSession, file: UploadFile) -> OrganizationSettings:
    """Validates, uploads the new logo, then swaps it into
    OrganizationSettings.logo_path — the old S3 object (if any) is deleted
    only after the new one is safely uploaded and persisted, so a mid-way
    failure never leaves the organization without a logo."""

    _validate_logo(file)

    settings = await _get_or_create_settings(db)
    old_logo_path = settings.logo_path

    s3_key = S3PathBuilder.organization_logo(file.filename)
    try:
        s3_service.upload_file(file, s3_key)
    except Exception:
        logger.exception("organization logo upload to S3 failed | filename=%s", file.filename)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to upload logo to storage. Please try again.",
        )

    settings = await update_organization_settings(db, settings, logo_path=s3_key)

    if old_logo_path:
        try:
            s3_service.delete_file(old_logo_path)
        except Exception:
            logger.exception("failed to delete replaced organization logo | key=%s", old_logo_path)

    return settings


async def delete_logo(db: AsyncSession) -> OrganizationSettings | None:
    """Idempotent: if there's no settings row yet, or no logo set, this is a
    no-op — deleting something that isn't there is not an error."""

    settings = await get_organization_settings(db)
    if settings is None or not settings.logo_path:
        return settings

    try:
        s3_service.delete_file(settings.logo_path)
    except Exception:
        logger.exception("failed to delete organization logo from S3 | key=%s", settings.logo_path)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to delete logo from storage. Please try again.",
        )

    return await update_organization_settings(db, settings, logo_path=None)
