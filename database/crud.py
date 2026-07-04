from datetime import datetime, timezone

from sqlalchemy.orm import Session

from database.models import User

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
