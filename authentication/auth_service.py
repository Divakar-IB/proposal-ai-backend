import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from authentication.hash import verify_password
from authentication.jwt_handler import (
    create_access_token,
    create_refresh_token,
)

from database.crud import (
    get_user_by_email,
    create_user_session,
    update_refresh_token,
)

from database.models import UserSession
from database.schemas import LoginRequest, LoginResponse


def login(db: Session,login_request: LoginRequest,) -> LoginResponse:
    user = get_user_by_email(db, login_request.email,)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(login_request.password, user.hashed_password,):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # Create Session
    session_uuid = str(uuid.uuid4())
    session = UserSession(
        user_id=user.id,
        session_uuid=session_uuid,
        refresh_token="",
    )

    create_user_session(db, session,)

    # Generate Tokens
    access_token = create_access_token(
        user_id=user.id,
        email=user.email,
        session_uuid=session_uuid,
    )

    refresh_token = create_refresh_token(
        user_id=user.id,
        session_uuid=session_uuid,
    )

    # Save Refresh Token
    update_refresh_token(
        db,
        session,
        refresh_token,
    )

    # Response
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )