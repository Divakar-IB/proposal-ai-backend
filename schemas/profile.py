from pydantic import BaseModel, EmailStr

from database.db_enum import UserRole


class ProfileResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: str | None = None
    designation: str | None = None
    role: UserRole

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    designation: str | None = None
