from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from authentication.hash import hash_password, verify_password
from authentication.jwt_handler import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from database.crud import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user_password,
)
from database.models import User
from schemas.auth import (
    CreatePasswordRequest,
    CreatePasswordResponse,
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
from middleware.auth_middleware import handle_exceptions
from utilities.helper import assign_role


@handle_exceptions
def login(db: Session, login_request: LoginRequest) -> LoginResponse:
    user = get_user_by_email(db, login_request.email)

    if user is None or not verify_password(login_request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact your administrator.",
        )
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )
    refresh_token = create_refresh_token(user_id=user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role.value,
        # is_first_login=user.is_first_login,
    )


@handle_exceptions
def register(db: Session, register_request: RegisterRequest) -> RegisterResponse:
    if get_user_by_email(db, register_request.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=register_request.email,
        hashed_password=hash_password(register_request.password),
        role=assign_role(register_request.role),
        is_first_login=True,
    )
    create_user(db, user)

    return RegisterResponse(message="Registered successfully", email=user.email)


@handle_exceptions
def refresh(db: Session, refresh_request: RefreshRequest) -> RefreshResponse:
    payload = verify_refresh_token(refresh_request.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = get_user_by_id(db, payload.get("user_id"))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    new_access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
    )
    return RefreshResponse(access_token=new_access_token)


# @handle_exceptions
# def logout(db: Session, logout_request: LogoutRequest) -> LogoutResponse:
#     session = get_user_session_by_refresh_token(db, logout_request.refresh_token)
#     if session is not None and session.is_active:
#         deactivate_user_session(db, session)
#     return LogoutResponse(message="Logged out successfully")


@handle_exceptions
def create_password(
    db: Session,
    request: CreatePasswordRequest,
    current_user: dict,
) -> CreatePasswordResponse:
    if request.new_password != request.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Passwords do not match",
        )

    user = get_user_by_id(db, current_user["user_id"])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not user.is_first_login:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password has already been set.",
        )

    update_user_password(db, user, hash_password(request.new_password))
    return CreatePasswordResponse(message="Password created successfully. You can now access the application.")


@handle_exceptions
def create_user_by_admin(
    db: Session,
    request: CreateUserRequest,
) -> CreateUserResponse:
    if get_user_by_email(db, request.email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=request.email,
        hashed_password=hash_password(request.password),
        role=request.role,
        is_first_login=True,
    )
    create_user(db, user)

    return CreateUserResponse(
        message="User created successfully. Share the registered email and password with the user.",
        email=user.email,
    )
