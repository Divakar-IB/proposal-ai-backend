from typing import Optional

from pydantic import BaseModel, EmailStr

from database.db_enum import UserRole


class ProfileResponse(BaseModel):
    id: int
    email: EmailStr
    full_name: Optional[str] = None
    designation: Optional[str] = None
    role: UserRole

    class Config:
        from_attributes = True


class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    designation: Optional[str] = None
