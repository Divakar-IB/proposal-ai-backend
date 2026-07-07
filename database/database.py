from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, scoped_session


DATABASE_URL = "postgresql+psycopg2://postgres:12345@localhost:5432/proposal_ai_dev"
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
