from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.auth_service import (
    create_user_by_admin,
    forgot_password,
    login,
    register,
    reset_password,
    set_new_password,
    verify_otp,
)
from authentication.dependency import get_current_user
from database.database import get_db
from database.db_enum import UserRole
from schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    NewPasswordRequest,
    NewPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    CreateUserRequest,
    CreateUserResponse,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    RegisterResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
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


@router.post("/forgot_password", response_model=ForgotPasswordResponse)
async def forgot_password_endpoint(
    forgot_password_request: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await forgot_password(db=db, request=forgot_password_request)


@router.post("/verify_otp", response_model=VerifyOtpResponse)
async def verify_otp_endpoint(
    verify_otp_request: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    return await verify_otp(db=db, request=verify_otp_request)


@router.post("/new_password", response_model=NewPasswordResponse)
async def new_password_endpoint(
    new_password_request: NewPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    return await set_new_password(db=db, request=new_password_request)


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
