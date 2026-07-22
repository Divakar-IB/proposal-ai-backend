from datetime import datetime, timezone

from sqlalchemy.orm import Session

<<<<<<< Updated upstream
from database.models import User, UserSession
=======
from database.db_enum import DocumentAvailability, ProposalStatus
from database.models import (
    Category,
    KnowledgeChunk,
    KnowledgeDocument,
    Proposal,
    ProposalSection,
    RequirementDocument,
    User,
)
>>>>>>> Stashed changes


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
<<<<<<< Updated upstream
=======
    return result.scalars().first()


def build_proposals_query(
    client_name: Optional[str] = None,
    proposal_status: Optional[ProposalStatus] = None,
) -> Select:
    query = select(Proposal).filter(Proposal.is_active.is_(True))
    if client_name:
        query = query.filter(Proposal.client_name.ilike(f"%{client_name}%"))
    if proposal_status is not None:
        query = query.filter(Proposal.status == proposal_status)
    return query.order_by(Proposal.created_at.desc())


async def update_proposal(db: AsyncSession, proposal: Proposal, **fields) -> Proposal:
    for key, value in fields.items():
        setattr(proposal, key, value)
    await db.commit()
    await db.refresh(proposal)
    return proposal
>>>>>>> Stashed changes


def update_refresh_token(db: Session, session: UserSession, refresh_token: str) -> UserSession:
    session.refresh_token = refresh_token
    db.commit()
    db.refresh(session)
    return session


def deactivate_user_session(db: Session, session: UserSession) -> None:
    session.is_active = False
    session.logout_at = datetime.now(timezone.utc)
    db.commit()
