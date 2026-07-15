from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
)

from sqlalchemy.orm import declarative_base, sessionmaker
from config import config


DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{config.database.username}:{config.database.password}"
    f"@{config.database.host}:{config.database.port}"
    f"/{config.database.db_name}"
    
)

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_recycle=1800,

    # connect_args={"ssl": True},
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
 
Base = declarative_base()


async def get_db():
    async with SessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


@asynccontextmanager
async def db_session():
    async with SessionLocal() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise