from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session
from config import config

# DATABASE_URL = "postgresql+psycopg2://postgres:12345@localhost:5432/proposal_ai_dev"
# DATABASE_URL = f"postgresql+psycopg2://neondb_owner:npg_wdDVx2PSgN9m@ep-morning-glitter-ao1eqs10.c-2.ap-southeast-1.aws.neon.tech/proposal_ai_dev?sslmode=require&channel_binding=require"
DATABASE_URL = (
    f"postgresql+psycopg2://"
    f"{config.database.username}:{config.database.password}"
    f"@{config.database.host}"
    f"/{config.database.db_name}"
    f"?sslmode={config.database.sslmode}"
    f"&channel_binding={config.database.channel_binding}"
)
engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=10,
            pool_recycle=1800,
            max_overflow=20,

        )

SessionLocal = scoped_session(sessionmaker(bind=engine,autoflush=False))
   
Base =  declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise

    finally:
        db.close()
        SessionLocal.remove()


@contextmanager
def db_session():
    """
    Session helper for code that runs outside the request lifecycle
    (e.g. BackgroundTasks), where the request-scoped get_db session is
    already closed by the time the task runs.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        SessionLocal.remove()
