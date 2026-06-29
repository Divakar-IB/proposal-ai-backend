from pydantic import BaseModel, EmailStr, field_validator

from database.db_enum import UserRole


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
    is_first_login: bool


# ------------------------------------------------------------------
# Register (Organization / Self-Service)
# ------------------------------------------------------------------
class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    is_organization: bool


class RegisterResponse(BaseModel):
    message: str
    email: EmailStr


# ------------------------------------------------------------------
# Refresh Token
# ------------------------------------------------------------------
class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ------------------------------------------------------------------
# Logout
# ------------------------------------------------------------------
class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    message: str


# ------------------------------------------------------------------
# Create Password (First Login)
# ------------------------------------------------------------------
class CreatePasswordRequest(BaseModel):
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class CreatePasswordResponse(BaseModel):
    message: str


# ------------------------------------------------------------------
# Create User (Admin only)
# ------------------------------------------------------------------
class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole


class CreateUserResponse(BaseModel):
    message: str
    email: EmailStr
