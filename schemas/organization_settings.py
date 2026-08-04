from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, field_validator


class OrganizationSettingsUpdateRequest(BaseModel):
    organization_name: str | None = None
    contact_email: str | None = None
    default_signee_name: str | None = None
    default_signee_designation: str | None = None
    proposal_naming_template: str | None = None

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError as error:
            raise ValueError(str(error))


class OrganizationSettingsResponse(BaseModel):
    id: int | None = None
    organization_name: str | None = None
    contact_email: str | None = None
    default_signee_name: str | None = None
    default_signee_designation: str | None = None
    proposal_naming_template: str | None = None
    logo_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True
