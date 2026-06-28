import uuid
from database.database import Base
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, JSON, func
from sqlalchemy.dialects.postgresql import ARRAY



# class Document(Base):
#     __tablename__ = "documents"

#     id = Column(Integer, primary_key=True, index=True)
#     filepath = Column(String, index=True)
#     upload_at = Column(DateTime, default=func.now())
#     type = Column(String, index=True)
#     text = Column(String, nullable=True)
#     template_id = Column(Integer, ForeignKey("templates.id"))
#     meta_data = Column(JSON, nullable=True)
#     user_id = Column(Integer, ForeignKey("users.id"))
#     created_at = Column(DateTime, default=func.now())
#     updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
#     is_active = Column(Boolean, default=True)

# class Template(Base):
#     __tablename__ = "templates"

#     id = Column(Integer, primary_key=True, index=True)
#     name = Column(String, index=True)
#     description = Column(String)
#     keywords = Column(ARRAY(String))
#     created_at = Column(DateTime, default=func.now())
#     updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
#     is_active = Column(Boolean, default=True)

# class User(Base):
#     __tablename__ = "users"

#     id = Column(Integer, primary_key=True, index=True)
#     name = Column(String, index=True)
#     mail = Column(String, unique=True, index=True)
#     password = Column(String)
#     logout = Column(Boolean, default=False)
#     created_at = Column(DateTime, default=func.now())
#     updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
#     is_active = Column(Boolean, default=True)

# class DocumentStatus(Base):
#     __tablename__ = "document_statuses"

#     id = Column(Integer, primary_key=True, index=True)
#     status = Column(String, index=True)
#     document_id = Column(Integer, ForeignKey("documents.id"))
#     is_approved = Column(Boolean, default=False)
#     created_at = Column(DateTime, default=func.now())
#     updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
#     is_active = Column(Boolean, default=True)

# class ClientDetails(Base):
#     __tablename__ = "client_details"

#     id = Column(Integer, primary_key=True, index=True)
#     requirement_name = Column(String, index=True)
#     description = Column(String)
#     client_name = Column(String, index=True)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime,default=func.now(),onupdate=func.now())
    is_active = Column(Boolean, default=True)

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token = Column(String, nullable=False)
    login_at = Column(DateTime, default=func.now())
    last_activity_at = Column(DateTime, default=func.now(), onupdate=func.now())
    logout_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)