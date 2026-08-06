from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Enum as SAEnum

import database.models  # noqa: F401 — side-effect import: registers models on Base.metadata before create_all
from config import config
from database.database import Base, engine
from database.db_enum import UserRole
from middleware.middleware import setup_middleware
from router import category, documents, organization_settings, profile, proposals, team
from router.auth_router import router as auth_router
from utilities.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Logged on every boot because a wrong mail transport is otherwise invisible:
    # forgot-password deliberately swallows send failures (see
    # authentication/auth_service.py::forgot_password), so a misconfigured
    # deployment still answers 200. Hosts that block outbound SMTP (Render among
    # them) need provider != "smtp" — see utilities/email_transport.py.
    logger.info(
        "mail transport | provider=%s host=%s port=%s from=%s",
        config.smtp.provider,
        config.smtp.host,
        config.smtp.port,
        config.smtp.from_email,
    )
    if config.smtp.provider == "smtp":
        logger.warning(
            "mail transport is plain SMTP — this fails on hosts that block outbound "
            "SMTP (Render: 'Network is unreachable'). Set smtp.provider to "
            "resend/brevo/sendgrid plus smtp.api_key when deploying there."
        )

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
app.include_router(organization_settings.router)
app.include_router(profile.router)
app.include_router(proposals.router)
app.include_router(team.router)


@app.get("/")
def root():
    return {"message": "Proposal AI Backend Running"}
