from pydantic import BaseModel, EmailStr, field_validator, ConfigDict

from database.db_enum import UserRole

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    role: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "role": "org_admin"
            }
        }
    )



# Register
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole

# Register Response
class RegisterResponse(BaseModel):
    message: str
    email: EmailStr

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "User registered successfully.",
                "email": "admin@example.com"
            }
        }
    )


# Refresh Token
class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer"
            }
        }
    )




# Logout
class LogoutRequest(BaseModel):
    refresh_token: str


class LogoutResponse(BaseModel):
    message: str


# Reset Password
class ResetPasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class ResetPasswordResponse(BaseModel):
    message: str


# Forgot Password
class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    message: str

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "message": "If this email is registered, an OTP has been sent to it."
            }
        }
    )


# Create User (Admin only)
class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    role: UserRole


class CreateUserResponse(BaseModel):
    message: str
    email: EmailStr
