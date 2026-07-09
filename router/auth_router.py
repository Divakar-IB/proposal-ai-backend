from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from authentication.auth_service import (
    create_user_by_admin,
    login,
    refresh,
    register,
    reset_password,
)
from authentication.dependency import get_current_user
from database.database import get_db
from database.db_enum import UserRole
from schemas.auth import (
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
    db: Session = Depends(get_db),
):
    return register(db=db, register_request=register_request)


@router.post("/login", response_model=LoginResponse)
async def login_user(
    login_request: LoginRequest,
    db: Session = Depends(get_db),
):
    return login(db=db, login_request=login_request)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    refresh_request: RefreshRequest,
    db: Session = Depends(get_db),
):
    return refresh(db=db, refresh_request=refresh_request)


# @router.post("/logout", response_model=LogoutResponse)
# def logout_user(
#     logout_request: LogoutRequest,
#     db: Session = Depends(get_db),
# ):
#     return logout(db=db, logout_request=logout_request)


@router.post("/reset_password", response_model=ResetPasswordResponse)
async def reset_user_password(
    reset_password_request: ResetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return reset_password(
        db=db,
        request=reset_password_request,
        current_user=current_user,
    )


@router.post("/create-user", response_model=CreateUserResponse)
async def create_user_endpoint(
    create_user_request: CreateUserRequest,
    db: Session = Depends(get_db),
    _: dict = Depends(require_role(UserRole.ADMIN)),
):
    return create_user_by_admin(db=db, request=create_user_request)
