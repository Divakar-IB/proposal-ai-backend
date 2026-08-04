from datetime import datetime

from pydantic import BaseModel, EmailStr

from database.db_enum import UserRole


class InviteTeamMemberRequest(BaseModel):
    email: EmailStr
    role: UserRole


class InviteTeamMemberResponse(BaseModel):
    message: str
    email: EmailStr
    role: UserRole


class TeamMemberResponse(BaseModel):
    id: int
    name: str | None = None
    email: EmailStr
    role: UserRole
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class TeamMemberListResponse(BaseModel):
    page: int
    limit: int
    total_pages: int
    total: int
    data: list[TeamMemberResponse]


class UpdateTeamMemberRoleRequest(BaseModel):
    role: UserRole


class UpdateTeamMemberRoleResponse(BaseModel):
    message: str
    id: int
    email: EmailStr
    role: UserRole


class UpdateTeamMemberStatusRequest(BaseModel):
    is_active: bool


class UpdateTeamMemberStatusResponse(BaseModel):
    message: str
    id: int
    email: EmailStr
    # "active" / "inactive" — same vocabulary as TeamMemberResponse.status so
    # the frontend can reuse one mapping.
    status: str
