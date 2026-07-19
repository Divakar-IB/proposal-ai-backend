from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.auth_service import (
    create_user_by_admin,
    forgot_password,
    login,
    refresh,
    register,
    reset_password,
)
from authentication.dependency import get_current_user
from database.database import get_db
from database.db_enum import UserRole
from schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    CreateUserRequest,
    CreateUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RefreshResponse,
    RegisterRequest,
    RegisterResponse,
)
from authentication.dependency import require_role

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post("/register", response_model=RegisterResponse)
async def register_user(
    register_request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    return await register(db=db, register_request=register_request)


@router.post("/login", response_model=LoginResponse)
async def login_user(
    login_request: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    return await login(db=db, login_request=login_request)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    refresh_request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    return await refresh(db=db, refresh_request=refresh_request)


# @router.post("/logout", response_model=LogoutResponse)
# def logout_user(
#     logout_request: LogoutRequest,
#     db: AsyncSession = Depends(get_db),
# ):
#     return logout(db=db, logout_request=logout_request)


@router.post("/forgot_password", response_model=ForgotPasswordResponse)
async def forgot_password_endpoint(
    forgot_password_request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await forgot_password(db=db, request=forgot_password_request)


@router.post("/reset_password", response_model=ResetPasswordResponse)
async def reset_user_password(
    reset_password_request: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return await reset_password(
        db=db,
        request=reset_password_request,
        current_user=current_user,
    )


@router.post("/create-user", response_model=CreateUserResponse)
async def create_user_endpoint(
    create_user_request: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    return await create_user_by_admin(db=db, request=create_user_request)
