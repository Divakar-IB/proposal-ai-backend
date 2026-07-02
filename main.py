from fastapi import FastAPI
from sqlalchemy import Enum as SAEnum
from sqlalchemy.exc import SQLAlchemyError

import database.models  # noqa: F401 — side-effect import: registers models on Base.metadata before create_all
from database.database import Base, engine
from database.db_enum import UserRole
from middleware.auth_middleware import generic_exception_handler, sqlalchemy_exception_handler
from router.auth_router import router as auth_router

# Idempotent: ensures the PG ENUM type exists even if the table was dropped while the type survived.
SAEnum(UserRole, name="userrole").create(bind=engine, checkfirst=True)
Base.metadata.create_all(bind=engine, checkfirst=True)

app = FastAPI(
    title="Proposal AI",
    version="1.0.0",
)

app.add_exception_handler(SQLAlchemyError, sqlalchemy_exception_handler)
app.add_exception_handler(Exception, generic_exception_handler)

app.include_router(auth_router)


@app.get("/")
def root():
    return {"message": "Proposal AI Backend Running"}
