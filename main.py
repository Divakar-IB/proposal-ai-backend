from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Enum as SAEnum

import database.models  # noqa: F401 — side-effect import: registers models on Base.metadata before create_all
from database.database import Base, engine
from database.db_enum import UserRole
from middleware.middleware import setup_middleware
from router.auth_router import router as auth_router
from router import category
from router import documents
from router import proposals, proposal_temp


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        # Idempotent: ensures the PG ENUM type exists even if the table was dropped while the type survived.
        await conn.run_sync(lambda sync_conn: SAEnum(UserRole, name="userrole").create(bind=sync_conn, checkfirst=True))
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    yield


app = FastAPI(
    title="Proposal AI",
    version="1.0.0",
    lifespan=lifespan,
)

setup_middleware(app)

app.include_router(auth_router)
app.include_router(category.router)
app.include_router(documents.router)
app.include_router(proposals.router)
app.include_router(proposal_temp.router)

@app.get("/")
def root():
    return {"message": "Proposal AI Backend Running"}
