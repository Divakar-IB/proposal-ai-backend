from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from authentication.dependency import hash_password, verify_password
from authentication.jwt_handler import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    verify_password_reset_token,
)
from database.crud import (
    clear_user_otp,
    create_user,
    get_user_by_email,
    get_user_by_id,
    set_user_otp,
    update_user_password,
)
from database.models import User
from schemas.auth import (
    CreateUserRequest,
    CreateUserResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LoginResponse,
    NewPasswordRequest,
    NewPasswordResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyOtpRequest,
    VerifyOtpResponse,
)
from utilities.email_service import send_otp_email
from utilities.generic import assign_role, generate_otp
from utilities.logger import get_logger

logger = get_logger(__name__)

OTP_EXPIRE_MINUTES = 10

GENERIC_FORGOT_PASSWORD_MESSAGE = "If this email is registered, an OTP has been sent to it."


async def login(db: AsyncSession, login_request: LoginRequest) -> LoginResponse:
    user = await get_user_by_email(db, login_request.email)

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


async def register(db: AsyncSession, register_request: RegisterRequest) -> RegisterResponse:
    if await get_user_by_email(db, register_request.email) is not None:
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
    await create_user(db, user)

    return RegisterResponse(message="Registered successfully", email=user.email)


async def reset_password(
    db: AsyncSession,
    request: ResetPasswordRequest,
    current_user: dict,
) -> ResetPasswordResponse:

    user = await get_user_by_id(db, current_user["user_id"])
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if not verify_password(request.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    await update_user_password(db, user, hash_password(request.new_password))
    return ResetPasswordResponse(message="Password reset successfully.")


async def forgot_password(
    db: AsyncSession,
    request: ForgotPasswordRequest,
) -> ForgotPasswordResponse:
    user = await get_user_by_email(db, request.email)

    # Always return a generic response so callers can't enumerate registered emails.
    if user is not None and user.is_active:
        otp = generate_otp()
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=OTP_EXPIRE_MINUTES)
        await set_user_otp(db, user, hash_password(otp), expires_at)
        try:
            await send_otp_email(user.email, otp, OTP_EXPIRE_MINUTES)
        except Exception:
            # Deliberately swallowed. Letting this propagate turned a mail
            # outage into a 500, which also defeated the generic response
            # above: a registered address 500'd while an unknown one returned
            # 200, so the endpoint leaked which emails exist. The OTP is
            # already stored, so a resend once mail is healthy still works.
            logger.exception("OTP email could not be sent | email=%s", user.email)

    return ForgotPasswordResponse(message=GENERIC_FORGOT_PASSWORD_MESSAGE)


def _check_otp(user: User | None, otp: str) -> None:
    invalid_otp_error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired OTP",
    )

    if user is None or not user.is_active or user.otp_code is None or user.otp_expires_at is None:
        raise invalid_otp_error

    if datetime.now(UTC).replace(tzinfo=None) > user.otp_expires_at:
        raise invalid_otp_error

    if not verify_password(otp, user.otp_code):
        raise invalid_otp_error


async def verify_otp(
    db: AsyncSession,
    request: VerifyOtpRequest,
) -> VerifyOtpResponse:
    user = await get_user_by_email(db, request.email)
    _check_otp(user, request.otp)

    # OTP is single-use: consume it now and hand back a short-lived reset
    # token so the follow-up /new_password call doesn't need the OTP again.
    await clear_user_otp(db, user)
    reset_token = create_password_reset_token(user.id, OTP_EXPIRE_MINUTES)

    return VerifyOtpResponse(message="OTP verified successfully.", reset_token=reset_token)


async def set_new_password(
    db: AsyncSession,
    request: NewPasswordRequest,
) -> NewPasswordResponse:
    payload = verify_password_reset_token(request.reset_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired reset token",
        )

    user = await get_user_by_id(db, payload.get("user_id"))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    await update_user_password(db, user, hash_password(request.new_password))
    return NewPasswordResponse(message="Password reset successfully.")


async def create_user_by_admin(
    db: AsyncSession,
    request: CreateUserRequest,
) -> CreateUserResponse:
    if await get_user_by_email(db, request.email) is not None:
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
    await create_user(db, user)

    return CreateUserResponse(
        message="User created successfully. Share the registered email and password with the user.",
        email=user.email,
    )
