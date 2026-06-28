from sqlalchemy.orm import Session

from database.models import User, UserSession
# ------------------------------------------------------------------
# User
# ------------------------------------------------------------------
def get_user_by_email(db: Session,email: str,):
    return (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

# ------------------------------------------------------------------
# User Session
# ------------------------------------------------------------------
def create_user_session(db: Session,session: UserSession,):
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_user_session(db: Session,session_uuid: str,):
    return (
        db.query(UserSession)
        .filter(UserSession.session_uuid == session_uuid)
        .first()
    )

def update_refresh_token(db: Session,session: UserSession,refresh_token: str,):
    session.refresh_token = refresh_token
    db.commit()
    db.refresh(session)
    return session

def delete_user_session(db: Session,session: UserSession,):
    db.delete(session)
    db.commit()