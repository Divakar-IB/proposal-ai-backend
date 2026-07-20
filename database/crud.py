from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from database.db_enum import DocumentAvailability
from database.models import (
    Category,
    KnowledgeChunk,
    KnowledgeDocument,
    Proposal,
    ProposalSection,
    RequirementDocument,
    User,
)


async def get_active_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category).filter(Category.is_active.is_(True)))
    return list(result.scalars().all())


async def has_any_knowledge_chunks(db: AsyncSession) -> bool:
    """Cheap existence check — lets callers skip embedding/Pinecone calls
    entirely when nothing has been indexed yet, rather than querying an
    empty (or not-yet-created) index and handling it after the fact."""
    result = await db.execute(select(KnowledgeChunk.id).limit(1))
    return result.scalars().first() is not None


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).filter(User.email == email))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()


async def create_user(db: AsyncSession, user: User) -> User:
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def update_user_password(db: AsyncSession, user: User, hashed_password: str) -> User:
    user.hashed_password = hashed_password
    user.is_first_login = False
    await db.commit()
    await db.refresh(user)
    return user


async def set_user_otp(db: AsyncSession, user: User, hashed_otp: str, expires_at: datetime) -> User:
    user.otp_code = hashed_otp
    user.otp_expires_at = expires_at
    await db.commit()
    await db.refresh(user)
    return user


async def get_knowledge_document_by_id(db: AsyncSession, document_id: int) -> KnowledgeDocument | None:
    result = await db.execute(
        select(KnowledgeDocument).filter(
            KnowledgeDocument.id == document_id, KnowledgeDocument.is_active.is_(True)
        )
    )
    return result.scalars().first()


def build_knowledge_documents_query(
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    knowledge_status: Optional[DocumentAvailability] = None,
) -> Select:
    query = select(KnowledgeDocument).filter(KnowledgeDocument.is_active.is_(True))
    if category_id is not None:
        query = query.filter(KnowledgeDocument.category_id == category_id)
    if search:
        query = query.filter(KnowledgeDocument.title.ilike(f"%{search}%"))
    if knowledge_status is not None:
        query = query.filter(KnowledgeDocument.availability_status == knowledge_status)
    return query.order_by(KnowledgeDocument.created_at.desc())


async def create_knowledge_document(db: AsyncSession, document: KnowledgeDocument) -> KnowledgeDocument:
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def update_knowledge_document(db: AsyncSession, document: KnowledgeDocument, **fields) -> KnowledgeDocument:
    for key, value in fields.items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


async def delete_knowledge_document(db: AsyncSession, document: KnowledgeDocument) -> None:
    document.is_active = False
    await db.commit()


async def delete_knowledge_chunks_for_document(db: AsyncSession, document_id: int) -> None:
    """Clears existing rows before re-processing a document (re-embed on a new version)."""
    await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_document_id == document_id))
    await db.commit()


async def create_knowledge_chunks(db: AsyncSession, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
    db.add_all(chunks)
    await db.commit()
    return chunks


# ------------------------------------------------------------------
# RequirementDocument
# ------------------------------------------------------------------

async def get_requirement_document_by_id(db: AsyncSession, document_id: int) -> RequirementDocument | None:
    result = await db.execute(
        select(RequirementDocument).filter(
            RequirementDocument.id == document_id, RequirementDocument.is_active.is_(True)
        )
    )
    return result.scalars().first()


async def create_requirement_document(db: AsyncSession, document: RequirementDocument) -> RequirementDocument:
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return document


async def update_requirement_document(
    db: AsyncSession, document: RequirementDocument, **fields
) -> RequirementDocument:
    for key, value in fields.items():
        setattr(document, key, value)
    await db.commit()
    await db.refresh(document)
    return document


# Proposal / ProposalSection
async def create_proposal(db: AsyncSession, proposal: Proposal) -> Proposal:
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def get_proposal_by_id(db: AsyncSession, proposal_id: int) -> Proposal | None:
    result = await db.execute(
        select(Proposal)
        .filter(Proposal.id == proposal_id, Proposal.is_active.is_(True))
    )
    return result.scalars().first()


async def update_proposal(db: AsyncSession, proposal: Proposal, **fields) -> Proposal:
    for key, value in fields.items():
        setattr(proposal, key, value)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def create_proposal_sections(
    db: AsyncSession, sections: list[ProposalSection]
) -> list[ProposalSection]:
    db.add_all(sections)
    await db.commit()
    return sections


async def update_proposal_section(
    db: AsyncSession, section: ProposalSection, **fields: Any
) -> ProposalSection:
    for key, value in fields.items():
        setattr(section, key, value)
    await db.commit()
    await db.refresh(section)
    return section
