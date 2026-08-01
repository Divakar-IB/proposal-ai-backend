from datetime import datetime
from typing import Optional

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, field_validator


class OrganizationSettingsUpdateRequest(BaseModel):
    organization_name: Optional[str] = None
    contact_email: Optional[str] = None
    default_signee_name: Optional[str] = None
    default_signee_designation: Optional[str] = None
    proposal_naming_template: Optional[str] = None

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError as error:
            raise ValueError(str(error))


class OrganizationSettingsResponse(BaseModel):
    id: Optional[int] = None
    organization_name: Optional[str] = None
    contact_email: Optional[str] = None
    default_signee_name: Optional[str] = None
    default_signee_designation: Optional[str] = None
    proposal_naming_template: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
