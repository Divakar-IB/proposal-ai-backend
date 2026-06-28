from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import config

USERNAME = config["DB"]["username"]
PASSWORD = config["DB"]["password"]
IP_ADDRESS = config["DB"]["ip_address"]
PORT = config["DB"]["port"]
DATABASE = config["DB"]["database"]

POOL_SIZE = config["DB"].get("pool_size", 40)
MAX_OVERFLOW = config["DB"].get("max_overflow", 10)
POOL_TIMEOUT = config["DB"].get("pool_timeout", 30)
POOL_RECYCLE = config["DB"].get("pool_recycle", 1800)


DATABASE_URL = (
    f"postgresql://"
    f"{USERNAME}:{PASSWORD}"
    f"@{IP_ADDRESS}:{PORT}"
    f"/{DATABASE}"
)

engine = create_engine(
    DATABASE_URL,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    pool_timeout=POOL_TIMEOUT,
    pool_recycle=POOL_RECYCLE,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)
Base = declarative_base()
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()