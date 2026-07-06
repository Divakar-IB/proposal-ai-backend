
from sqlalchemy import (
    Column, 
    Integer, 
    String, 
    DateTime, 
    ForeignKey, 
    Boolean, 
    Enum as SAEnum, 
    func, 
    Text
)
from sqlalchemy.orm import relationship

from database.database import Base
from database.db_enum import UserRole, IngestionStatus, DocumentStatus


class BasicModel(Base):
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class User(BasicModel):
    __tablename__ = "users"

    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(UserRole, name="userrole"), nullable=False, default=UserRole.USER)
    is_first_login = Column(Boolean, default=True)
    knowledge_documents = relationship("KnowledgeDocument", back_populates="uploader")
    requirement_documents = relationship("RequirementDocument", back_populates="uploader")

class Category(BasicModel):
    __tablename__ = "categories"

    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text,nullable=True)
    knowledge_document = relationship("KnowledgeDocument", back_populates="category")


class KnowledgeDocument(BasicModel):
    __tablename__ = "knowledge_documents"

    title = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    # stored_file_name = Column(String(255), unique=True)
    file_path = Column(Text, nullable=False)
    extension = Column(String(20), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    version = Column(Integer, default=1)
    status = Column(SAEnum(IngestionStatus),nullable= False, default=IngestionStatus.PENDING)
    
    category = relationship("Category", back_populates="knowledge_document")
    uploader = relationship("User", back_populates="knowledge_documents")


class RequirementDocument(BasicModel):
    __tablename__ = "requirement_documents"

    file_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    extension = Column(String(20), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(SAEnum(DocumentStatus), nullable= False, default=DocumentStatus.UPLOADING)
    uploader = relationship("User", back_populates="requirement_documents")