from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    ForeignKey,
    Integer,
    String,
    Text,
    Enum as SAEnum,
    func,
)
from sqlalchemy import Enum as SAEnum

from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base
from database.db_enum import (
    UserRole,
    IngestionStatus,
    DocumentStatus,
    DocumentAvailability,
    ProposalStatus,
    ProposalSectionStatus,
)


class BasicModel(Base):
    __abstract__ = True

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())


class User(BasicModel):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="userrole"), nullable=False, default=UserRole.USER
    )
    is_first_login: Mapped[bool] = mapped_column(default=True)

    knowledge_documents: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="uploader")
    requirement_documents: Mapped[list["RequirementDocument"]] = relationship(back_populates="uploader")


class Category(BasicModel):
    __tablename__ = "categories"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    knowledge_document: Mapped[list["KnowledgeDocument"]] = relationship(back_populates="category")


class KnowledgeDocument(BasicModel):
    __tablename__ = "knowledge_documents"

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    version: Mapped[int] = mapped_column(default=1)
    tags: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String), nullable=True)
    status: Mapped[IngestionStatus] = mapped_column(
        SAEnum(IngestionStatus), nullable=False, default=IngestionStatus.PENDING
    )
    availability_status: Mapped[DocumentAvailability] = mapped_column(
        SAEnum(DocumentAvailability, name="availability"),
        nullable=False,
        default=DocumentAvailability.ACTIVE,
    )
    # extracted_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    category: Mapped["Category"] = relationship(back_populates="knowledge_document", lazy="selectin")
    uploader: Mapped["User"] = relationship(back_populates="knowledge_documents")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeChunk(BasicModel):
    """Postgres source of truth for chunks embedded into Pinecone (Path A)."""

    __tablename__ = "knowledge_chunks"

    knowledge_document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    breadcrumb: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pinecone_vector_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")


class RequirementDocument(BasicModel):
    __tablename__ = "requirement_documents"

    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), nullable=False, default=DocumentStatus.UPLOADING
    )
    extracted_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parsed_data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    uploader: Mapped["User"] = relationship(back_populates="requirement_documents")
    proposals: Mapped[list["Proposal"]] = relationship(back_populates="requirement_document")


class Proposal(BasicModel):
    __tablename__ = "proposals"

    requirement_document_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_documents.id"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ProposalStatus] = mapped_column(
        SAEnum(ProposalStatus), nullable=False, default=ProposalStatus.DRAFT
    )
    markdown_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    docx_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    requirement_document: Mapped["RequirementDocument"] = relationship(back_populates="proposals")
    sections: Mapped[list["ProposalSection"]] = relationship(
        back_populates="proposal",
        cascade="all, delete-orphan",
        order_by="ProposalSection.order_index",
        lazy="selectin",
    )


class ProposalSection(BasicModel):
    __tablename__ = "proposal_sections"

    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposals.id"), nullable=False, index=True)
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    citations: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[ProposalSectionStatus] = mapped_column(
        SAEnum(ProposalSectionStatus), nullable=False, default=ProposalSectionStatus.PENDING
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    proposal: Mapped["Proposal"] = relationship(back_populates="sections")
