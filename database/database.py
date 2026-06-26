from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from config import config
db_config = config["DB"]

DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{db_config['username']}:{db_config['password']}"
    f"@{db_config['ip_address']}:{db_config['port']}"
    f"/{db_config['database']}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=db_config.get("pool_size", 40),
    max_overflow=db_config.get("max_overflow", 10),
    pool_timeout=db_config.get("pool_timeout", 30),
    pool_recycle=db_config.get("pool_recycle", 1800),
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine,)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()