"""Shared test fixtures.

The suite runs the *real* FastAPI app (routers, middleware, Pydantic schemas,
JWT auth, SQLAlchemy models) against a throwaway in-memory SQLite database.
Only the things that would reach outside this process are replaced: S3, SMTP,
Pinecone and the LLM/generation pipeline.

Two things need care and are handled here once:

* ``config.py`` reads a single ``CONFIG`` env var at import time, so it is set
  at the very top of this module — before anything imports the app.
* The models use Postgres-only column types (``JSONB``, ``ARRAY``). They are
  given SQLite variants via ``with_variant`` so the same metadata can build the
  test schema without changing production behaviour.
"""

import json
import os

# Must run before any app module is imported. python-dotenv (called inside
# config.py) does not override variables that are already set, so this wins
# over the developer's real .env.
os.environ["CONFIG"] = json.dumps(
    {
        "database": {
            "username": "test",
            "password": "test",
            "host": "localhost",
            "port": 5432,
            "db_name": "test",
            "pool_size": 1,
            "max_overflow": 0,
            "pool_recycle": 1800,
            "pool_timeout": 30,
        },
        "jwt": {
            "secret_key": "test-secret-key-not-used-anywhere-real",
            "algorithm": "HS256",
            "access_token_expire_minutes": 60,
            "refresh_token_expire_days": 7,
            "issuer": "proposal-ai",
        },
        "aws": {
            "access_key_id": "testing",
            "secret_access_key": "testing",
            "region": "us-east-1",
            "bucket_name": "test-bucket",
        },
        "pinecone": {
            "api_key": "test-pinecone-key",
            "index_name": "test-index",
            "dimension": 1024,
            "metric": "cosine",
            "cloud": "aws",
            "region": "us-east-1",
        },
        "groq": {
            "api_key": "test-groq-key",
            "base_url": "https://api.groq.com/openai/v1",
            "llm_model": "openai/gpt-oss-120b",
        },
        "hf_inference": {
            "api_token": "test-hf-token",
            "embedding_model": "BAAI/bge-m3",
            "hf_base_api_url": "https://router.huggingface.co/hf-inference/models/",
        },
        "smtp": {
            "host": "localhost",
            "port": 587,
            "username": "test@example.com",
            "password": "test",
            "from_email": "test@example.com",
            "use_tls": True,
            "provider": "smtp",
        },
        "redis": {"host": "localhost", "port": 6379, "db": 0},
        "allowed_origins": ["http://localhost:3000"],
    }
)

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from helpers import TEST_PASSWORD, auth_headers  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import JSON, String  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY as PostgresARRAY  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlalchemy.types import TEXT, TypeDecorator  # noqa: E402

# bcrypt is deliberately expensive, and the suite hashes a password for nearly
# every user it creates — at the production work factor that alone dominates the
# run. Turn it down to the minimum for tests; the real bcrypt code path (and
# every hash/verify call site) is still exercised.
import authentication.dependency as auth_dependency  # noqa: E402
import database.database as database_module  # noqa: E402
import main  # noqa: E402
from authentication.dependency import hash_password  # noqa: E402
from database.database import Base, get_db  # noqa: E402
from database.db_enum import (  # noqa: E402
    DocumentAvailability,
    DocumentStatus,
    IngestionStatus,
    ProposalSectionStatus,
    ProposalStatus,
    UserRole,
)
from database.models import (  # noqa: E402
    Category,
    KnowledgeChunk,
    KnowledgeDocument,
    OrganizationSettings,
    Proposal,
    ProposalSection,
    RequirementDocument,
    User,
)
from utilities.s3_service import S3Service  # noqa: E402

auth_dependency.pwd_context.update(bcrypt__default_rounds=4)


# ------------------------------------------------------------------
# Postgres-only column types -> SQLite equivalents
# ------------------------------------------------------------------


class _JsonEncodedList(TypeDecorator):
    """Stand-in for Postgres ``ARRAY(String)``: stores the list as a JSON blob
    so ``KnowledgeDocument.tags`` round-trips as a real Python list."""

    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(list(value))

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)


def _add_sqlite_variants() -> None:
    """`with_variant` leaves the Postgres type in place for every other
    dialect, so production DDL/behaviour is untouched — SQLite just gets a
    compatible stand-in."""

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSONB().with_variant(JSON(), "sqlite")
            elif isinstance(column.type, PostgresARRAY):
                column.type = PostgresARRAY(String).with_variant(_JsonEncodedList(), "sqlite")


_add_sqlite_variants()


# ------------------------------------------------------------------
# Database
# ------------------------------------------------------------------


@pytest.fixture
async def engine():
    """A fresh in-memory database per test.

    StaticPool keeps every session on the same connection, which is what makes
    ``:memory:`` visible across sessions at all — without it each new
    connection would get its own empty database.
    """

    test_engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)


@pytest.fixture
async def db(session_factory):
    """Session for *arranging* test data, separate from the one the request
    handler gets (same underlying connection, so writes are visible to both)."""

    async with session_factory() as session:
        yield session


@pytest.fixture
def app(session_factory, monkeypatch):
    """The real app, with only the DB dependency swapped out.

    ``database.SessionLocal`` is repointed too: background tasks and the SSE
    generator open their own session via ``db_session()`` rather than the
    request-scoped one, and that path must not reach for Postgres.
    """

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(database_module, "SessionLocal", session_factory)
    main.app.dependency_overrides[get_db] = override_get_db
    try:
        yield main.app
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


# ------------------------------------------------------------------
# Outbound dependencies — never hit the network from a test
# ------------------------------------------------------------------


class FakeS3:
    """Records what the app tried to do with S3 so tests can assert on it."""

    def __init__(self):
        self.uploaded: list[str] = []
        self.deleted: list[str] = []
        self.upload_error: Exception | None = None
        self.delete_error: Exception | None = None

    def upload_file(self, file, file_path: str):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded.append(file_path)
        return file_path

    def upload_bytes(self, data: bytes, file_path: str, content_type: str = "application/octet-stream"):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded.append(file_path)
        return file_path

    def delete_file(self, file_path: str):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(file_path)

    def generate_presigned_url(self, file_path: str, expires_in: int = 3600):
        return f"https://s3.test/{file_path}?signed=1"

    def download_file(self, file_path: str) -> bytes:
        return b"file-bytes"


@pytest.fixture(autouse=True)
def fake_s3(monkeypatch):
    """Patched on the class, not on an instance: several routers build their
    own module-level ``S3Service()`` at import time, and this catches them all."""

    fake = FakeS3()

    def forward(method):
        # Swallows the S3Service `self` the class-level lookup supplies and
        # forwards to the single shared FakeS3 recorder.
        def wrapper(_s3_service_self, *args, **kwargs):
            return method(*args, **kwargs)

        return wrapper

    for name in (
        "upload_file",
        "upload_bytes",
        "delete_file",
        "generate_presigned_url",
        "download_file",
    ):
        monkeypatch.setattr(S3Service, name, forward(getattr(fake, name)))
    return fake


class SentEmail:
    def __init__(self, kind: str, args: tuple, kwargs: dict):
        self.kind = kind
        self.args = args
        self.kwargs = kwargs


@pytest.fixture(autouse=True)
def sent_emails(monkeypatch):
    """Collects outbound mail. Patched where each sender is *used* (the modules
    import the functions by name), not on utilities.email_service."""

    import authentication.auth_service as auth_service
    import services.proposal_export_service as export_service
    import services.team_service as team_service

    sent: list[SentEmail] = []

    def recorder(kind: str):
        async def _send(*args, **kwargs):
            sent.append(SentEmail(kind, args, kwargs))

        return _send

    monkeypatch.setattr(auth_service, "send_otp_email", recorder("otp"))
    monkeypatch.setattr(team_service, "send_team_invite_email", recorder("invite"))
    monkeypatch.setattr(export_service, "send_proposal_export_email", recorder("export"))
    return sent


@pytest.fixture(autouse=True)
def stub_background_pipelines(monkeypatch):
    """Replaces every long-running / third-party pipeline the routers kick off.

    ``BackgroundTasks`` really do run under ASGITransport, so without this a
    document upload would try to OCR a fake PDF and talk to Pinecone.
    Returns a dict of call-recording lists so tests can assert scheduling.
    """

    import router.documents as documents_router
    import router.proposals as proposals_router

    calls: dict[str, list] = {
        "process_knowledge_document": [],
        "delete_document_vectors": [],
        "ingest_proposal_as_knowledge": [],
        "process_requirement_document_pipeline": [],
    }

    async def fake_process_knowledge_document(document_id: int):
        calls["process_knowledge_document"].append(document_id)

    def fake_delete_document_vectors(document_id: int):
        calls["delete_document_vectors"].append(document_id)

    async def fake_ingest_proposal_as_knowledge(proposal_id: int):
        calls["ingest_proposal_as_knowledge"].append(proposal_id)

    async def fake_requirement_pipeline(db, document, additional_context=None):
        """Mimics a successful parse: the real pipeline mutates and returns the
        same RequirementDocument row."""

        calls["process_requirement_document_pipeline"].append(document.id)
        document.status = DocumentStatus.PARSED
        document.extracted_markdown = "# Requirements\n\nBuild a thing."
        document.summary = f"Summary for {document.file_name}"
        document.parsed_data = {"project_title": "Website Revamp"}
        document.capability_tags = [{"name": "Backend Development", "confidence": 0.9}]
        document.knowledge_matches = []
        await db.commit()
        await db.refresh(document)
        return document

    monkeypatch.setattr(documents_router, "process_knowledge_document", fake_process_knowledge_document)
    monkeypatch.setattr(documents_router, "delete_document_vectors", fake_delete_document_vectors)
    monkeypatch.setattr(proposals_router, "ingest_proposal_as_knowledge", fake_ingest_proposal_as_knowledge)
    monkeypatch.setattr(proposals_router, "process_requirement_document_pipeline", fake_requirement_pipeline)

    return calls


@pytest.fixture
def stub_renderers(monkeypatch):
    """Replaces all three native rendering steps — the export tests care about
    the endpoint contract, not the bytes.

    `render_proposal_html` has to be stubbed alongside the PDF/DOCX renderers:
    it converts every section's Markdown with `pypandoc`, so it needs the
    external `pandoc` binary even for a PDF export. Leaving it live made these
    tests pass or fail depending on whether pandoc was installed and had memory
    to run.
    """

    import services.proposal_export_service as export_service

    monkeypatch.setattr(export_service, "render_proposal_html", lambda *args, **kwargs: "<html>fake</html>")
    monkeypatch.setattr(export_service, "render_pdf_from_html", lambda html: b"%PDF-1.7 fake")
    monkeypatch.setattr(
        export_service,
        "render_docx_from_html",
        lambda html, reference_docx=None: b"PK\x03\x04 fake-docx",
    )


# ------------------------------------------------------------------
# Data factories
# ------------------------------------------------------------------


class Factory:
    """Thin helpers over the ORM — every test that needs a row builds it here
    rather than going through the API, so arrange steps stay independent of the
    endpoints under test."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._counter = 0

    def _next(self) -> int:
        self._counter += 1
        return self._counter

    async def _add(self, instance):
        self.session.add(instance)
        await self.session.commit()
        await self.session.refresh(instance)
        return instance

    async def user(
        self,
        *,
        email: str | None = None,
        password: str = TEST_PASSWORD,
        role: UserRole = UserRole.USER,
        is_active: bool = True,
        full_name: str | None = None,
        designation: str | None = None,
        otp_code: str | None = None,
        otp_expires_at: datetime | None = None,
    ) -> User:
        return await self._add(
            User(
                email=email or f"user{self._next()}@example.com",
                hashed_password=hash_password(password),
                role=role,
                is_active=is_active,
                full_name=full_name,
                designation=designation,
                otp_code=hash_password(otp_code) if otp_code else None,
                otp_expires_at=otp_expires_at,
            )
        )

    async def admin(self, **kwargs) -> User:
        kwargs.setdefault("role", UserRole.ADMIN)
        return await self.user(**kwargs)

    async def category(self, *, name: str | None = None, description: str = "desc", is_active: bool = True) -> Category:
        return await self._add(
            Category(name=name or f"Category {self._next()}", description=description, is_active=is_active)
        )

    async def knowledge_document(
        self,
        *,
        user: User,
        category: Category,
        title: str | None = None,
        status: IngestionStatus = IngestionStatus.INDEXED,
        availability_status: DocumentAvailability = DocumentAvailability.ACTIVE,
        tags: list[str] | None = None,
        is_active: bool = True,
        source_proposal_id: int | None = None,
    ) -> KnowledgeDocument:
        index = self._next()
        return await self._add(
            KnowledgeDocument(
                title=title or f"Document {index}",
                description="A knowledge document",
                file_name=f"doc{index}.pdf",
                file_path=f"input/knowledge/{user.id}/{category.id}/{index}/file.pdf",
                extension="pdf",
                category_id=category.id,
                user_id=user.id,
                tags=tags if tags is not None else [],
                status=status,
                availability_status=availability_status,
                is_active=is_active,
                source_proposal_id=source_proposal_id,
            )
        )

    async def knowledge_chunk(self, *, document: KnowledgeDocument, chunk_index: int = 0) -> KnowledgeChunk:
        return await self._add(
            KnowledgeChunk(
                knowledge_document_id=document.id,
                chunk_index=chunk_index,
                breadcrumb="Root > Section",
                content="chunk content",
                token_count=3,
                pinecone_vector_id=f"doc-{document.id}-chunk-{chunk_index}",
            )
        )

    async def proposal(
        self,
        *,
        user: User,
        title: str | None = None,
        client_name: str = "Acme Corp",
        status: ProposalStatus = ProposalStatus.INPROGRESS,
        is_active: bool = True,
        generation_mode=None,
        page_count: int | None = None,
        created_at: datetime | None = None,
    ) -> Proposal:
        proposal = Proposal(
            user_id=user.id,
            title=title or f"Proposal {self._next()}",
            client_name=client_name,
            additional_context="Some context",
            status=status,
            is_active=is_active,
            generation_mode=generation_mode,
            page_count=page_count,
        )
        if created_at is not None:
            proposal.created_at = created_at
        return await self._add(proposal)

    async def section(
        self,
        *,
        proposal: Proposal,
        section_key: str | None = None,
        title: str | None = None,
        order_index: int = 0,
        content: str = "Section body.",
        status: ProposalSectionStatus = ProposalSectionStatus.APPROVED,
    ) -> ProposalSection:
        index = self._next()
        section = await self._add(
            ProposalSection(
                proposal_id=proposal.id,
                section_key=section_key or f"section_{index}",
                title=title or f"Section {index}",
                order_index=order_index,
                content=content,
                citations=[],
                status=status,
            )
        )
        await self.session.refresh(proposal)
        return section

    async def requirement_document(
        self,
        *,
        user: User,
        proposal: Proposal | None = None,
        status: DocumentStatus = DocumentStatus.PARSED,
        summary: str | None = "A summary",
        parsed_data: dict | None = None,
        capability_tags: list[dict] | None = None,
        knowledge_matches: list[dict] | None = None,
    ) -> RequirementDocument:
        index = self._next()
        return await self._add(
            RequirementDocument(
                file_name=f"rfp{index}.pdf",
                file_path=f"input/requirements/{user.id}/{index}/file.pdf",
                extension="pdf",
                user_id=user.id,
                proposal_id=proposal.id if proposal else None,
                status=status,
                summary=summary,
                parsed_data=parsed_data,
                capability_tags=capability_tags,
                knowledge_matches=knowledge_matches,
            )
        )

    async def organization_settings(self, **fields) -> OrganizationSettings:
        fields.setdefault("organization_name", "Innoboon")
        fields.setdefault("contact_email", "hello@innoboon.com")
        return await self._add(OrganizationSettings(**fields))


@pytest.fixture
def factory(db) -> Factory:
    return Factory(db)


# ------------------------------------------------------------------
# Auth fixtures (auth_headers itself lives in helpers.py)
# ------------------------------------------------------------------


@pytest.fixture
async def member(factory) -> User:
    return await factory.user(email="member@example.com", role=UserRole.USER)


@pytest.fixture
async def admin(factory) -> User:
    return await factory.user(email="admin@example.com", role=UserRole.ADMIN)


@pytest.fixture
def member_headers(member) -> dict[str, str]:
    return auth_headers(member)


@pytest.fixture
def admin_headers(admin) -> dict[str, str]:
    return auth_headers(admin)
