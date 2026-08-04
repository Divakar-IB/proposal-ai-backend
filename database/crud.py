from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, load_only, selectinload
from sqlalchemy.sql import Select

from database.db_enum import DocumentAvailability, ProposalStatus
from database.models import (
    Category,
    KnowledgeChunk,
    KnowledgeDocument,
    OrganizationSettings,
    Proposal,
    ProposalSection,
    RequirementDocument,
    User,
)


async def get_active_categories(db: AsyncSession) -> list[Category]:
    result = await db.execute(select(Category).filter(Category.is_active.is_(True)))
    return list(result.scalars().all())


async def get_category_by_name(db: AsyncSession, name: str) -> Category | None:
    result = await db.execute(select(Category).filter(Category.name == name, Category.is_active.is_(True)))
    return result.scalars().first()


async def get_category_by_name_including_deleted(db: AsyncSession, name: str) -> Category | None:
    """Ignores is_active on purpose. Category.name carries a DB-level UNIQUE
    constraint, so a soft-deleted row keeps its name reserved — callers that
    are about to INSERT must look for the hidden row first and revive it
    instead, or the insert fails with an IntegrityError."""

    result = await db.execute(select(Category).filter(Category.name == name))
    return result.scalars().first()


async def get_category_by_id(db: AsyncSession, category_id: int) -> Category | None:
    result = await db.execute(select(Category).filter(Category.id == category_id, Category.is_active.is_(True)))
    return result.scalars().first()


async def count_active_documents_in_category(db: AsyncSession, category_id: int) -> int:
    result = await db.execute(
        select(func.count(KnowledgeDocument.id)).filter(
            KnowledgeDocument.category_id == category_id,
            KnowledgeDocument.is_active.is_(True),
        )
    )
    return int(result.scalar_one())


async def deactivate_category(db: AsyncSession, category: Category) -> None:
    category.is_active = False
    await db.commit()


async def reactivate_category(db: AsyncSession, category: Category, description: str | None = None) -> Category:
    """Brings a soft-deleted category back rather than inserting a second row
    with the same (UNIQUE) name."""

    category.is_active = True
    if description is not None:
        category.description = description
    await db.commit()
    await db.refresh(category)
    return category


async def create_category(db: AsyncSession, category: Category) -> Category:
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def get_or_create_category(db: AsyncSession, name: str) -> Category:
    """Used to lazily provision system categories (e.g. "Generated
    Proposals" for proposal-derived knowledge documents) without requiring
    an admin to create them by hand first.

    Revives a soft-deleted category of the same name instead of inserting a
    duplicate — deleting "Generated Proposals" would otherwise make every
    later proposal approval fail on the UNIQUE(name) constraint."""

    category = await get_category_by_name(db, name)
    if category is not None:
        return category

    deleted = await get_category_by_name_including_deleted(db, name)
    if deleted is not None:
        return await reactivate_category(db, deleted)

    return await create_category(db, Category(name=name))


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


async def update_user(db: AsyncSession, user: User, **fields: Any) -> User:
    for key, value in fields.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    user.is_active = False
    await db.commit()


def build_users_query() -> Select:
    # Only the columns router/team.py::_to_response actually renders. Notably
    # this keeps hashed_password and otp_code out of the result set — no reason
    # to pull credential material into memory to build a member listing.
    return (
        select(User)
        .options(
            load_only(
                User.id,
                User.full_name,
                User.email,
                User.role,
                User.is_active,
                User.created_at,
            )
        )
        .order_by(User.created_at.desc())
    )


async def set_user_otp(db: AsyncSession, user: User, hashed_otp: str, expires_at: datetime) -> User:
    user.otp_code = hashed_otp
    user.otp_expires_at = expires_at
    await db.commit()
    await db.refresh(user)
    return user


async def clear_user_otp(db: AsyncSession, user: User) -> User:
    user.otp_code = None
    user.otp_expires_at = None
    await db.commit()
    await db.refresh(user)
    return user


async def get_knowledge_document_by_id(db: AsyncSession, document_id: int) -> KnowledgeDocument | None:
    result = await db.execute(
        select(KnowledgeDocument).filter(KnowledgeDocument.id == document_id, KnowledgeDocument.is_active.is_(True))
    )
    return result.scalars().first()


async def get_knowledge_documents_by_ids(db: AsyncSession, document_ids: list[int]) -> list[KnowledgeDocument]:
    if not document_ids:
        return []
    result = await db.execute(
        select(KnowledgeDocument).filter(KnowledgeDocument.id.in_(document_ids), KnowledgeDocument.is_active.is_(True))
    )
    return list(result.scalars().all())


def build_knowledge_documents_query(
    category_id: int | None = None,
    search: str | None = None,
    knowledge_status: DocumentAvailability | None = None,
    include_generated: bool = False,
) -> Select:
    """`include_generated=False` (the default) hides documents that were
    auto-ingested from an approved proposal (source_proposal_id is set) — the
    manual-upload listing shouldn't silently mix in proposal-derived entries
    unless a caller explicitly asks to see them."""

    # extracted_markdown holds the document's full text — easily hundreds of KB
    # across a page of results — and DocumentResponse never exposes it. Defer
    # it so a listing does not haul the entire knowledge base over the wire.
    # (The ingestion pipeline reads it via get_knowledge_document_by_id, which
    # is unaffected.)
    query = (
        select(KnowledgeDocument)
        .options(defer(KnowledgeDocument.extracted_markdown))
        .filter(KnowledgeDocument.is_active.is_(True))
    )
    if not include_generated:
        query = query.filter(KnowledgeDocument.source_proposal_id.is_(None))
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


async def get_requirement_documents_by_proposal_id(db: AsyncSession, proposal_id: int) -> list[RequirementDocument]:
    result = await db.execute(
        select(RequirementDocument)
        .filter(
            RequirementDocument.proposal_id == proposal_id,
            RequirementDocument.is_active.is_(True),
        )
        .order_by(RequirementDocument.created_at)
    )
    return list(result.scalars().all())


async def update_requirement_document(db: AsyncSession, document: RequirementDocument, **fields) -> RequirementDocument:
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


# Proposal.requirement_documents is eagerly loaded (lazy="selectin"), which by
# default pulls every column of each RequirementDocument — including
# extracted_markdown, parsed_data, capability_tags and knowledge_matches. Those
# average ~22 KB per document on real data, and the only thing any consumer
# reads off this relationship is `.id` (router/proposals.py builds
# `requirement_document_ids` from it).
#
# Restricting the eager load to the primary key keeps the relationship
# populated exactly as before while dropping ~22 KB per document per request.
# raiseload=True makes a future access to any other column fail immediately
# with a clear SQLAlchemy error instead of emitting a silent extra query (or,
# under asyncio, a confusing MissingGreenlet) — if you need more columns here,
# widen this load_only rather than removing it.
_REQUIREMENT_DOCUMENT_IDS_ONLY = selectinload(Proposal.requirement_documents).load_only(
    RequirementDocument.id, raiseload=True
)


async def get_proposal_by_id(db: AsyncSession, proposal_id: int) -> Proposal | None:
    result = await db.execute(
        select(Proposal)
        .options(_REQUIREMENT_DOCUMENT_IDS_ONLY)
        .filter(Proposal.id == proposal_id, Proposal.is_active.is_(True))
    )
    return result.scalars().first()


def build_proposals_query(
    search: str | None = None,
    proposal_status: ProposalStatus | None = None,
    created_by: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> Select:
    query = select(Proposal).options(_REQUIREMENT_DOCUMENT_IDS_ONLY).filter(Proposal.is_active.is_(True))
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Proposal.title.ilike(pattern), Proposal.client_name.ilike(pattern)))
    if proposal_status is not None:
        query = query.filter(Proposal.status == proposal_status)
    if created_by is not None:
        query = query.filter(Proposal.user_id == created_by)
    if created_from is not None:
        query = query.filter(Proposal.created_at >= created_from)
    if created_to is not None:
        query = query.filter(Proposal.created_at <= created_to)
    return query.order_by(Proposal.created_at.desc())


async def get_proposal_status_counts(db: AsyncSession, *, created_by: int | None = None) -> dict[ProposalStatus, int]:
    query = (
        select(Proposal.status, func.count(Proposal.id)).filter(Proposal.is_active.is_(True)).group_by(Proposal.status)
    )
    if created_by is not None:
        query = query.filter(Proposal.user_id == created_by)
    result = await db.execute(query)
    return dict(result.all())


async def update_proposal(db: AsyncSession, proposal: Proposal, **fields) -> Proposal:
    for key, value in fields.items():
        setattr(proposal, key, value)
    await db.commit()
    await db.refresh(proposal)
    return proposal


async def delete_proposal(db: AsyncSession, proposal: Proposal) -> None:
    proposal.is_active = False
    await db.commit()


async def create_proposal_sections(db: AsyncSession, sections: list[ProposalSection]) -> list[ProposalSection]:
    db.add_all(sections)
    await db.commit()
    return sections


async def delete_proposal_sections_for_proposal(db: AsyncSession, proposal_id: int) -> None:
    """Wipes prior sections before storing a fresh generation — avoids stale/
    duplicate rows on regeneration."""

    result = await db.execute(select(ProposalSection).filter(ProposalSection.proposal_id == proposal_id))
    for section in result.scalars().all():
        await db.delete(section)
    await db.commit()


async def update_proposal_section(db: AsyncSession, section: ProposalSection, **fields: Any) -> ProposalSection:
    for key, value in fields.items():
        setattr(section, key, value)
    await db.commit()
    await db.refresh(section)
    return section


async def get_proposal_section_by_id(db: AsyncSession, section_id: int) -> ProposalSection | None:
    result = await db.execute(
        select(ProposalSection).filter(ProposalSection.id == section_id, ProposalSection.is_active.is_(True))
    )
    return result.scalars().first()


async def get_proposal_sections_by_ids(db: AsyncSession, section_ids: list[int]) -> list[ProposalSection]:
    result = await db.execute(
        select(ProposalSection).filter(ProposalSection.id.in_(section_ids), ProposalSection.is_active.is_(True))
    )
    return list(result.scalars().all())


# OrganizationSettings — single-row table, no id-based lookup needed
async def get_organization_settings(db: AsyncSession) -> OrganizationSettings | None:
    result = await db.execute(select(OrganizationSettings).filter(OrganizationSettings.is_active.is_(True)).limit(1))
    return result.scalars().first()


async def create_organization_settings(db: AsyncSession, settings: OrganizationSettings) -> OrganizationSettings:
    db.add(settings)
    await db.commit()
    await db.refresh(settings)
    return settings


async def update_organization_settings(
    db: AsyncSession, settings: OrganizationSettings, **fields: Any
) -> OrganizationSettings:
    for key, value in fields.items():
        setattr(settings, key, value)
    await db.commit()
    await db.refresh(settings)
    return settings
