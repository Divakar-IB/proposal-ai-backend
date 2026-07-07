from fastapi import FastAPI
from sqlalchemy import Enum as SAEnum

import database.models  # noqa: F401 — side-effect import: registers models on Base.metadata before create_all
from database.database import Base, engine
from database.db_enum import UserRole
from middleware.auth_middleware import setup_middleware
from router.auth_router import router as auth_router
from router import category
from router import documents

# Idempotent: ensures the PG ENUM type exists even if the table was dropped while the type survived.
SAEnum(UserRole, name="userrole").create(bind=engine, checkfirst=True)
Base.metadata.create_all(bind=engine, checkfirst=True)

app = FastAPI(
    title="Proposal AI",
    version="1.0.0",
)

setup_middleware(app)

app.include_router(auth_router)
app.include_router(category.router)
app.include_router(documents.router)

@app.get("/")
def root():
    return {"message": "Proposal AI Backend Running"}
