from database.database import Base
from database.db_enum import UserRole
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Enum as SAEnum, func


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(UserRole, name="userrole"), nullable=False, default=UserRole.USER)
    is_first_login = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token = Column(String, nullable=False)
    login_at = Column(DateTime, default=func.now())
    logout_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
