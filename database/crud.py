from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from database.models import KnowledgeDocument, User

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


def get_knowledge_document_by_id(db: Session, document_id: int) -> KnowledgeDocument | None:
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.id == document_id, KnowledgeDocument.is_active.is_(True))
        .first()
    )


def get_knowledge_documents(db: Session, category_id: Optional[int] = None) -> list[KnowledgeDocument]:
    query = db.query(KnowledgeDocument).filter(KnowledgeDocument.is_active.is_(True))
    if category_id is not None:
        query = query.filter(KnowledgeDocument.category_id == category_id)
    return query.order_by(KnowledgeDocument.created_at.desc()).all()


def create_knowledge_document(db: Session, document: KnowledgeDocument) -> KnowledgeDocument:
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def update_knowledge_document(db: Session, document: KnowledgeDocument, **fields) -> KnowledgeDocument:
    for key, value in fields.items():
        setattr(document, key, value)
    db.commit()
    db.refresh(document)
    return document


def delete_knowledge_document(db: Session, document: KnowledgeDocument) -> None:
    document.is_active = False
    db.commit()
