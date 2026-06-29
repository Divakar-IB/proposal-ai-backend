from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database.models import User, UserSession


# ------------------------------------------------------------------
# User
# ------------------------------------------------------------------
def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def create_user(db: Session, user: User) -> User:
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_password(db: Session, user: User, hashed_password: str) -> User:
    user.hashed_password = hashed_password
    user.is_first_login = False
    db.commit()
    db.refresh(user)
    return user


# ------------------------------------------------------------------
# User Session
# ------------------------------------------------------------------
def create_user_session(db: Session, session: UserSession) -> UserSession:
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_user_session_by_refresh_token(db: Session, refresh_token: str) -> UserSession | None:
    return (
        db.query(UserSession)
        .filter(
            UserSession.refresh_token == refresh_token,
            UserSession.is_active == True,
        )
        .first()
    )


def update_refresh_token(db: Session, session: UserSession, refresh_token: str) -> UserSession:
    session.refresh_token = refresh_token
    db.commit()
    db.refresh(session)
    return session


def deactivate_user_session(db: Session, session: UserSession) -> None:
    session.is_active = False
    session.logout_at = datetime.now(timezone.utc)
    db.commit()
