# Testing Guide

API test suite for the Proposal AI backend. Every endpoint is exercised against
the **real** FastAPI application — real routers, real middleware, real Pydantic
schemas, real JWT auth, real SQLAlchemy models — backed by a throwaway in-memory
SQLite database standing in for Postgres.

No Postgres, no Docker, no Redis, no network access, no credentials required.

```
395 tests   →   392 passed, 3 xfailed, 0 failed      (~16 seconds)
```

The 3 `xfailed` are **not breakage**. They are deliberate markers pinning three
real bugs found in the application code — see [Why 3 tests "fail"](#why-3-tests-fail).

---

## Table of contents

1. [Quick start](#1-quick-start)
2. [Design principles](#2-design-principles)
3. [How a test runs, end to end](#3-how-a-test-runs-end-to-end)
4. [How the database is connected](#4-how-the-database-is-connected)
5. [Fixture reference](#5-fixture-reference)
6. [How authentication works in tests](#6-how-authentication-works-in-tests)
7. [Data factories](#7-data-factories)
8. [Cases handled, per router](#8-cases-handled-per-router)
9. [Why 3 tests "fail"](#9-why-3-tests-fail)
10. [Writing a new test](#10-writing-a-new-test)
11. [Troubleshooting and gotchas](#11-troubleshooting-and-gotchas)

---

## 1. Quick start

```bash
pytest                                    # everything
pytest test/test_proposals.py             # one module
pytest test/test_auth.py -k otp           # matching tests
pytest -x                                 # stop at first failure
pytest -q --tb=short                      # quieter output, short tracebacks
pytest -rx                                # list the xfail reasons
pytest --runxfail                         # run the xfails for real (3 will fail — by design)
pytest --collect-only -q                  # list tests without running them
```

### Dependencies

Three test-only packages, declared in `pyproject.toml` under
`[dependency-groups] dev`:

| Package | Version | Purpose |
|---|---|---|
| `pytest` | 8.4.2 | runner |
| `pytest-asyncio` | 1.3.0 | `async def` test support |
| `aiosqlite` | 0.21.0 | async SQLite driver — the mock database |
| `httpx` | 0.28.1 | already a transitive dep; drives the ASGI app |

Install:

```bash
uv pip install pytest==8.4.2 pytest-asyncio==1.3.0 aiosqlite==0.21.0
```

> `uv.lock` has **not** been regenerated for the `dev` group. Run `uv lock` if
> you want these pinned in the lockfile.

### Configuration

All of it lives in `pyproject.toml` — there is no `pytest.ini` or `setup.cfg`:

```toml
[tool.pytest.ini_options]
testpaths = ["test"]
pythonpath = ["."]                              # ← see note below
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
addopts = "-q --strict-markers"
filterwarnings = ["ignore::DeprecationWarning"]
```

Two settings are load-bearing:

- **`pythonpath = ["."]`** — the tests import app modules by their top-level
  names (`main`, `router.proposals`, `database.crud`). By default pytest only
  puts the *test* directory on `sys.path`, so without this every import fails.
- **`asyncio_mode = "auto"`** — every `async def test_*` is treated as an asyncio
  test with no `@pytest.mark.asyncio` decorator needed. `loop_scope = "function"`
  gives each test its own event loop, which is what lets the per-test async
  database engine work cleanly.

### Layout

```
test/
├── conftest.py                       fixtures, DB setup, stubs, factories
├── helpers.py                        plain helpers (auth_headers, upload, time)
├── test_smoke.py               3     harness sanity checks
├── test_hash.py               21     bcrypt + JWT primitives
├── test_auth.py               49     /auth
├── test_profile.py            11     /profile
├── test_team.py               35     /team
├── test_category.py           25     /category
├── test_documents.py          39     /document
├── test_organization_settings.py 35  /organization-settings
├── test_proposals.py          92     /proposal
├── test_proposal_wizard.py    23     /proposal/{id}/state, /proposal/{id}/sections
├── test_generation_pipeline.py 49    the generation pipeline itself (not a router)
└── test_middleware.py         13     error handler, CORS, routing, OpenAPI
```

`test_generation_pipeline.py` is the one module that drives the real generation
pipeline rather than an endpoint. `test_proposals.py` stubs
`generate_proposal_stream` wholesale to test the endpoint's SSE plumbing, so
without this nothing exercises `generation/graph.py`, `section_runner.py`,
`token_budget.py` or `rate_limit.py` — the layers where a section can come back
empty. See [Generation pipeline](#generation-pipeline--test_generation_pipelinepy-49).

---

## 2. Design principles

The suite draws one line: **everything inside the process is real; everything
that leaves the process is stubbed.**

### Real — never mocked

| Component | Why it stays real |
|---|---|
| The FastAPI app (`main.app`) | Routing, `response_model` validation, dependency wiring and status codes are exactly what production runs |
| Middleware | `ErrorHandlerMiddleware` + CORS are in the request path, so error mapping is genuinely tested |
| JWT auth | Tokens are minted by your own `jwt_handler`; `HTTPBearer` → `verify_access_token` → issuer check → token-type check → `require_role` all execute |
| Pydantic schemas | Every 422 in this suite is a real validation failure, not an asserted constant |
| SQLAlchemy models + `database/crud.py` | Relationships, `lazy="selectin"`, `load_only`, `defer`, soft-delete filters and cascades all behave as written |
| bcrypt hashing | Real `passlib`/`bcrypt`, just at a lower work factor |

### Stubbed — because it would leave the process

| Component | Replaced with |
|---|---|
| Postgres | in-memory SQLite (`aiosqlite`) |
| AWS S3 | `FakeS3` — records calls, can be made to fail |
| SMTP / email providers | recorder that appends to `sent_emails` |
| Pinecone | `delete_document_vectors` recorded, never called |
| Groq / HF Inference | unreachable — the pipelines that call them are stubbed |
| PaddleOCR / PyMuPDF extraction | `process_knowledge_document` stubbed |
| WeasyPrint (PDF) | `render_pdf_from_html` → fixed bytes |
| Pandoc (DOCX + Markdown→HTML) | `render_docx_from_html`, `render_proposal_html` → fixed values |

**The auth dependency is deliberately *not* overridden.** Many FastAPI suites do
`app.dependency_overrides[get_current_user] = lambda: {...}`, which silently
stops testing authentication. Here, tests build a genuine signed token instead —
which is what makes the forged-signature, wrong-issuer, expired-token and
refresh-token-used-as-access-token cases meaningful.

---

## 3. How a test runs, end to end

```
pytest invoked
  │
  ├─► reads [tool.pytest.ini_options] from pyproject.toml
  │
  ├─► imports test/conftest.py                          ← ONCE per session
  │     ①  os.environ["CONFIG"] = {test json}              must be first
  │     ②  import main                                     real app (~14s cold)
  │     ③  _add_sqlite_variants()                          JSONB/ARRAY → SQLite
  │     ④  pwd_context.update(bcrypt__default_rounds=4)    speed
  │
  ├─► collects test modules
  │
  └─► FOR EACH TEST FUNCTION
        │
        ├─ fixture setup (in dependency order)
        │    engine ──────────► new :memory: DB + Base.metadata.create_all
        │    session_factory ─► async_sessionmaker bound to it
        │    db ─────────────► AsyncSession for arranging data
        │    factory ────────► ORM row builders using `db`
        │    app ────────────► main.app + dependency_overrides[get_db]
        │                      + database.SessionLocal repointed
        │    client ─────────► httpx.AsyncClient over ASGITransport(app)
        │    [autouse] ──────► fake_s3, sent_emails, stub_background_pipelines
        │
        ├─ ARRANGE   user = await factory.user(role=UserRole.ADMIN)
        │            proposal = await factory.proposal(user=user)
        │
        ├─ ACT       response = await client.post(..., headers=auth_headers(user))
        │              → ASGITransport calls the real app in-process
        │              → CORS → ErrorHandler → routing → dependencies
        │              → get_current_user decodes the real JWT
        │              → endpoint runs against SQLite
        │              → BackgroundTasks run (stubbed) before the call returns
        │
        ├─ ASSERT    response.status_code / response.json()
        │            + DB state via `db`
        │            + side effects via fake_s3 / sent_emails / stub_background_pipelines
        │
        └─ teardown  monkeypatch undone, overrides cleared, engine disposed
                     → the in-memory database ceases to exist
```

### Why the ordering in conftest matters

**① `CONFIG` before any app import.** `config.py` builds `AppConfig()` at module
import time and requires a `CONFIG` env var holding a JSON blob. It also calls
`load_dotenv()`, which does **not** overwrite an env var that already exists.
Setting `os.environ["CONFIG"]` at the very top of `conftest.py` therefore wins
over your real `.env`, and tests can never touch production credentials. Every
import below it carries `# noqa: E402` because the order is intentional.

**② `import main` is unavoidable and slow.** `main` → `router.documents` →
`tasks.document_processing` → `extraction.factory` → `paddleocr`. That chain
costs roughly 14 seconds on a cold filesystem cache. It happens once, at
conftest import, then everything is cached for the rest of the session.

**④ bcrypt work factor.** bcrypt is deliberately expensive, and the suite hashes
a password for nearly every user it creates. At the production work factor that
alone dominated the run — **121 seconds**. Dropping to the minimum rounds for
tests brought the whole suite to **15 seconds** while still executing the real
bcrypt code path at every call site:

```python
import authentication.dependency as auth_dependency
auth_dependency.pwd_context.update(bcrypt__default_rounds=4)
```

### Note on `BackgroundTasks`

Under `httpx.ASGITransport`, `BackgroundTasks` **really run** — `httpx` awaits
the full ASGI call, and Starlette executes background tasks before it completes.
Without `stub_background_pipelines`, a single document upload would attempt to
OCR a fake PDF, call Hugging Face for embeddings, and upsert to Pinecone. This
is also what makes it possible to assert *scheduling* rather than guessing.

Conversely, **the lifespan handler does not run** under `ASGITransport` — which
is exactly what you want, since `main.py`'s lifespan calls `create_all` against
the production Postgres engine.

---

## 4. How the database is connected

The core problem: the models are Postgres-specific, but a mock database should
be in-process and disposable. Three obstacles, three solutions.

### 4.1 Postgres-only column types

These columns cannot exist in SQLite as written:

| Model | Column | Type |
|---|---|---|
| `KnowledgeDocument` | `tags` | `ARRAY(String)` |
| `RequirementDocument` | `parsed_data`, `capability_tags`, `knowledge_matches` | `JSONB` |
| `ProposalSection` | `citations` | `JSONB` |

Rather than editing the models, dialect-specific variants are attached to the
metadata at conftest import:

```python
class _JsonEncodedList(TypeDecorator):
    """Stand-in for Postgres ARRAY(String): stores the list as a JSON blob
    so KnowledgeDocument.tags round-trips as a real Python list."""
    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else json.dumps(list(value))

    def process_result_value(self, value, dialect):
        return None if value is None else json.loads(value)


def _add_sqlite_variants() -> None:
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSONB().with_variant(JSON(), "sqlite")
            elif isinstance(column.type, PostgresARRAY):
                column.type = PostgresARRAY(String).with_variant(_JsonEncodedList(), "sqlite")
```

`with_variant` is SQLAlchemy's supported mechanism for exactly this: the
Postgres type remains authoritative for every other dialect, and only the
`"sqlite"` dialect sees the stand-in. **Production DDL and behaviour are
untouched** — production never uses the SQLite dialect.

`test_postgres_only_columns_round_trip` in `test_smoke.py` guards this, asserting
that `document.tags == ["a", "b"]` and `requirement.parsed_data == {...}` survive
a write/read cycle.

Two things needed no work at all:

- **`Enum` columns** — SQLAlchemy renders `SAEnum` as `VARCHAR` + a `CHECK`
  constraint on SQLite. (Note that SQLAlchemy stores the enum *name*, e.g.
  `ADMIN`, not the value `org_admin` — identical on both backends.)
- **`func.now()` defaults** — compile to `CURRENT_TIMESTAMP`.

### 4.2 Making `:memory:` visible across sessions

```python
@pytest.fixture
async def engine():
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
```

**`StaticPool` is load-bearing.** With `:memory:`, *each connection gets its own
empty database*. A default pool hands out a fresh connection per checkout, so
the `db` fixture would write rows the request handler could never see.
`StaticPool` pins every session to a single shared connection.

`check_same_thread: False` is required because SQLAlchemy's async layer drives
the sync sqlite3 driver from a worker greenlet.

**The fixture is function-scoped on purpose.** At teardown the entire database
ceases to exist, so every test starts from an empty schema. That gives perfect
isolation with no truncation or transaction-rollback machinery, and creating 8
SQLite tables is sub-millisecond. Every test module also passes when run alone —
verified.

### 4.3 Pointing the application at the test database

The codebase has **two** ways of obtaining a session, and both need redirecting:

```python
@pytest.fixture
def app(session_factory, monkeypatch):
    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    monkeypatch.setattr(database_module, "SessionLocal", session_factory)   # ②
    main.app.dependency_overrides[get_db] = override_get_db                 # ①
    try:
        yield main.app
    finally:
        main.app.dependency_overrides.clear()
```

- **① `dependency_overrides[get_db]`** covers request-scoped work — every
  endpoint using `db: AsyncSession = Depends(get_db)`. The override mirrors the
  real `get_db` exactly: yield, commit on success, rollback and re-raise on
  error. That fidelity matters, because it's what makes
  `test_renaming_onto_a_soft_deleted_name_currently_500s` observe the real
  `IntegrityError` → 503 path.
- **② `SessionLocal` repointed** covers anything running *after* the request
  returns. Background tasks and the SSE generator open their own session via
  `async with db_session():`, which reads `database.SessionLocal` at call time.
  Without this line a stray background task would reach for production Postgres.

The `db` fixture and the request handler use *different sessions on the same
connection*, so writes are mutually visible. Because factories always commit and
every test awaits sequentially, there is no concurrency hazard.

`expire_on_commit=False` matches the production `SessionLocal`, so ORM objects
returned by factories stay usable after a commit.

---

## 5. Fixture reference

All in `test/conftest.py`.

### Database and client

| Fixture | Scope | Description |
|---|---|---|
| `engine` | function | Fresh in-memory SQLite engine with the full schema created |
| `session_factory` | function | `async_sessionmaker` bound to `engine` |
| `db` | function | `AsyncSession` for arranging and inspecting data |
| `app` | function | `main.app` with `get_db` overridden and `SessionLocal` repointed |
| `client` | function | `httpx.AsyncClient` over `ASGITransport(app)`, base URL `http://testserver` |

### Users and auth

| Fixture | Description |
|---|---|
| `factory` | `Factory` instance bound to `db` — see [§7](#7-data-factories) |
| `member` | A `UserRole.USER` at `member@example.com` |
| `admin` | A `UserRole.ADMIN` at `admin@example.com` |
| `member_headers` | `Authorization: Bearer <token>` for `member` |
| `admin_headers` | Same, for `admin` |

### Outbound stubs

Three are **autouse** — they apply to every test whether requested or not, so no
test can accidentally reach the network. Request them by name only when you need
to assert on or manipulate them.

#### `fake_s3` (autouse)

```python
class FakeS3:
    uploaded: list[str]              # keys the app tried to upload
    deleted: list[str]               # keys the app tried to delete
    upload_error: Exception | None   # set this to make uploads fail
    delete_error: Exception | None   # set this to make deletes fail
```

`generate_presigned_url` returns a deterministic `https://s3.test/{key}?signed=1`,
which is why tests can assert on exact URLs.

Patched on the **class**, not on an instance — `router/documents.py`,
`router/proposals.py`, `router/organization_settings.py`
and `services/organization_settings_service.py` each construct their own
module-level `S3Service()` at import time, so only a class-level patch catches
them all. A small `forward()` wrapper swallows the `S3Service` `self` that the
class-level lookup supplies:

```python
def forward(method):
    def wrapper(_s3_service_self, *args, **kwargs):
        return method(*args, **kwargs)
    return wrapper
```

#### `sent_emails` (autouse)

A `list[SentEmail]`, each with `.kind` (`"otp"` / `"invite"` / `"export"`),
`.args` and `.kwargs`.

Patched where each sender is **used**, not on `utilities.email_service` — the
consuming modules do `from utilities.email_service import send_otp_email`, which
binds the function into their own namespace, so patching the source module would
have no effect:

```python
monkeypatch.setattr(auth_service,   "send_otp_email",             recorder("otp"))
monkeypatch.setattr(team_service,   "send_team_invite_email",     recorder("invite"))
monkeypatch.setattr(export_service, "send_proposal_export_email", recorder("export"))
```

#### `stub_background_pipelines` (autouse)

Returns a dict of call-recording lists:

```python
{
    "process_knowledge_document":            [document_id, ...],
    "delete_document_vectors":               [document_id, ...],
    "ingest_proposal_as_knowledge":          [proposal_id, ...],
    "process_requirement_document_pipeline": [document_id, ...],
}
```

`process_requirement_document_pipeline` is not a bare recorder — it mimics a
successful parse, because the real one mutates and returns the same row and the
endpoint reads the result back into its response:

```python
async def fake_requirement_pipeline(db, document, additional_context=None):
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
```

That fixed `project_title` is what the auto-naming tests assert against
(`"Acme Corp - Website Revamp Proposal"`).

#### `stub_renderers` (opt-in)

Requested explicitly by the export tests. Stubs **all three** native rendering
steps:

```python
monkeypatch.setattr(export_service, "render_proposal_html",  lambda *a, **k: "<html>fake</html>")
monkeypatch.setattr(export_service, "render_pdf_from_html",  lambda html: b"%PDF-1.7 fake")
monkeypatch.setattr(export_service, "render_docx_from_html", lambda html, reference_docx=None: b"PK\x03\x04 fake-docx")
```

`render_proposal_html` **must** be included. It converts every section's Markdown
with `pypandoc`, so it needs the external `pandoc` binary even for a PDF export.
Leaving it live made the export tests pass or fail depending on whether pandoc
was installed and had memory to run — a real defect in an earlier version of
this harness. See [bug 3](#bug-3--export-returns-an-opaque-500-when-pandoc-is-unavailable).

---

## 6. How authentication works in tests

There is no `dependency_overrides[get_current_user]`. `test/helpers.py` mints a
genuine token through the application's own JWT code:

```python
def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user_id=user.id, email=user.email, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}
```

The signing key comes from the test `CONFIG`, so tokens are valid but useless
outside the suite. Every authenticated request therefore executes:

```
HTTPBearer            → 401 "Not authenticated" if the header is missing/malformed
verify_access_token   → signature, issuer ("proposal-ai") and exp checks
                      → token_type must be "access" (rejects refresh/reset tokens)
get_current_user      → 401 on any failure
require_role(ADMIN)   → 403 "You do not have permission to perform this action."
```

Verified in this FastAPI version (0.138.0): a missing header, an empty
credential, a wrong scheme and a malformed JWT **all return 401**, not 403.
Admin-only routes return 403 only for a *valid* token whose role is insufficient.

### Usage patterns

```python
# convenience fixtures for the common case
async def test_x(client, admin_headers): ...
async def test_y(client, member_headers): ...

# explicit user when the test needs the row itself
async def test_z(client, factory):
    user = await factory.user(email="a@example.com", role=UserRole.ADMIN)
    response = await client.get("/profile", headers=auth_headers(user))

# no headers at all, to assert the 401
async def test_requires_auth(client):
    assert (await client.get("/profile")).status_code == 401
```

---

## 7. Data factories

`Factory` (in `conftest.py`, exposed as the `factory` fixture) builds rows
directly through the ORM, so arrange steps never depend on the endpoints under
test. Names are auto-generated from an internal counter when not supplied.

| Method | Notable keyword arguments |
|---|---|
| `user(...)` | `email`, `password`, `role`, `is_active`, `full_name`, `designation`, `otp_code`, `otp_expires_at` |
| `admin(...)` | same, `role` defaults to `ADMIN` |
| `category(...)` | `name`, `description`, `is_active` |
| `knowledge_document(...)` | `user`*, `category`*, `title`, `status`, `availability_status`, `tags`, `is_active`, `source_proposal_id` |
| `knowledge_chunk(...)` | `document`*, `chunk_index` |
| `proposal(...)` | `user`*, `title`, `client_name`, `status`, `is_active`, `generation_mode`, `page_count`, `created_at` |
| `section(...)` | `proposal`*, `section_key`, `title`, `order_index`, `content`, `status` |
| `requirement_document(...)` | `user`*, `proposal`, `status`, `summary`, `parsed_data`, `capability_tags`, `knowledge_matches` |
| `organization_settings(...)` | any `OrganizationSettings` column |

`*` = required.

Two details worth knowing:

- `user(otp_code="123456")` **hashes** the OTP on the way in, matching how
  `forgot_password` stores it — so the OTP tests can post the plaintext code.
- `section()` refreshes the parent proposal afterwards, so
  `proposal.sections` is populated for the caller.
- `proposal(created_at=...)` sets the timestamp explicitly, which is how the
  `created_from` / `created_to` filter tests work.

```python
async def test_example(client, factory):
    admin = await factory.admin()
    category = await factory.category(name="Case Studies")
    document = await factory.knowledge_document(
        user=admin, category=category, tags=["aws"],
    )
```

---

## 8. Cases handled, per router

Beyond happy paths, the suite systematically covers: authentication and
authorization on every protected route, soft-delete invisibility, forward-only
status transitions, S3 and SMTP failure injection, background-task scheduling,
partial-update vs. explicit-null semantics, multipart edge cases, and
route-ordering traps.

The number after each heading is the module's **collected** test count, so the
three modules holding an xfail (`test_auth`, `test_category`, `test_proposals`)
include it.

### `/auth` — `test_auth.py` (49)

| Endpoint | Cases |
|---|---|
| `POST /register` | success; password hashed and `is_first_login=True`; duplicate → 409; **duplicate of a soft-deleted user → 409** (`get_user_by_email` ignores `is_active`, so a removed member's address stays reserved); 5 validation shapes |
| `POST /login` | tokens + role; the returned token actually works on a protected route; wrong password → 401; unknown email → 401 **with an identical message** (no account enumeration); inactive → 403; bad email → 422 |
| `POST /forgot_password` | OTP stored and mailed; unknown email → same generic 200 with no mail; inactive user → 200 with no OTP written; **SMTP outage → still 200, OTP persisted** (a 500 here would leak which addresses exist, defeating the generic response) |
| `POST /verify_otp` | returns reset token and clears the OTP; **single-use** (2nd call → 400); expired → 400; wrong code → 400; no pending OTP → 400; unknown email → 400; inactive → 400 |
| `POST /new_password` | full flow — old password stops working, new one works; garbage token → 401; **access token rejected**; **refresh token rejected**; expired → 401; user removed after issue → 404; <8 chars → 422 |
| `POST /reset_password` | success; wrong current password → 401; confirm mismatch → 422; too short → 422; deleted user → 404 |
| `POST /create-user` | admin succeeds and **the role is honoured verbatim**; duplicate → 409; member → 403 |
| Token handling | missing / empty credential / wrong scheme / malformed JWT → 401; **foreign signature** → 401; refresh token as bearer → 401 |

Contains **[bug 1](#bug-1--every-self-registered-user-becomes-org_admin)** (xfail).

### `/profile` — `test_profile.py` (11)

Token owner returned; valid token pointing at a nonexistent row → **404, not
500**; partial update leaves omitted fields alone (`exclude_unset`); explicit
`null` clears one field without touching others; empty body is a no-op;
**email and role cannot be changed** — they're outside `UpdateProfileRequest`, so
extra keys are dropped (asserted on both the response *and* the DB row);
wrong field type → 422; unauthenticated → 401; `?user_id=` tampering is ignored
because identity comes only from the token.

### `/team` — `test_team.py` (35)

| Group | Cases |
|---|---|
| Invite | member created and temp password mailed, **and the password is absent from the response body**; existing email → 409; **mail failure → 502 but the account survives** (a retry would hit the 409, so the distinct 502 is what tells the admin to resend); member → 403; no token → 401; 3 validation shapes |
| List | pagination metadata; **`hashed_password` / `otp_code` absent** (the `load_only` in `build_users_query`); deactivated members still listed as `inactive`; page/limit slicing with no overlap between pages; **page past the end → 404 "No data available"**; member → 403 |
| Role | promote; demote while another admin remains; **demoting the last remaining admin → 400**; own role → 400; unknown → 404; unknown role → 422; member → 403 |
| Status | deactivate then login → 403; reactivate then login → 200; **idempotent** no-op; self-deactivate → 400; last admin → 400; unknown → 404; missing flag → 422; member → 403 |
| Delete | soft-deletes but stays listed as `inactive`; not repeatable (2nd → 404); own account → 400; last admin → 400; unknown → 404; member → 403 |

The last-admin cases need a specific setup: the guard counts *active* admins, so
the acting admin is deactivated first, leaving exactly one active admin while the
actor still holds a valid token.

### `/category` — `test_category.py` (25)

Create; duplicate active name → 400; **a soft-deleted name is revived rather
than rejected** (`name` is UNIQUE and deletion is soft, so this is the only way a
name can ever be reused); name and description both required. Update by id;
unknown id → 404; name taken by another active category → 400; **a category can
keep its own name** (the check excludes the row being edited). List with document
counts; soft-deleted categories hidden; **only active documents counted**; empty
list. Delete → 204 and gone from the listing; unknown → 404; already deleted →
404; **409 while documents still reference it, with the count and category name
in the message**; soft-deleted documents don't block deletion; non-integer id → 422.

Contains **[bug 2](#bug-2--renaming-a-category-onto-a-soft-deleted-name-returns-503)** (xfail).

### `/document` — `test_documents.py` (39)

| Group | Cases |
|---|---|
| Create | full response shape, S3 key prefix, background task scheduled; **a `user_id` in the form body is ignored in favour of the token**; tags stored; explicit `availability_status`; each of name/category/file missing → 422 naming that field; **a blank-filename part is treated as no file**; unknown category → 404; soft-deleted category → 404; **S3 failure → 502 and no DB row** (upload first, database second) |
| Edit | metadata-only change leaves `version` at 1, uploads nothing and **schedules no re-index**; file replacement bumps `version`, deletes the old object and **schedules re-chunk/re-embed**; move to another category; unknown category → 404; unknown document → 404; soft-deleted → 404; a no-field edit is a no-op; **failed replacement → 502, the row still points at the good object**, `version` unchanged, nothing deleted |
| List | pagination; empty → 200 not 404; category filter; **case-insensitive title search**; availability filter; **`include_generated` hides proposal-derived documents by default**; soft-deleted excluded; combined filters; unknown status → 422 |
| Get | success including `category_name`; unknown → 404; soft-deleted → 404; **`/document/list` not swallowed by `/{document_id}`**; non-integer id → 422 |
| Delete | 204 + S3 object deleted + **Pinecone vectors deleted** + `knowledge_chunks` rows removed + row soft-deleted; unknown → 404; not repeatable |

### `/organization-settings` — `test_organization_settings.py` (35)

No row → **all-null response, not 404**; stored row returned; logo path
presigned; member → 403. `PUT` creates, then updates *the same* row (asserted by
id); omitted fields untouched; explicit `null` clears; contact email normalised;
empty string → null; invalid → 422; empty body creates an all-null row.

Logo: upload plus presigned URL; **the old object is deleted only after the new
one lands**; **a failed cleanup of the replaced object does not fail the
request** (the new logo is already live — an orphan in the bucket is the lesser
evil); 5 rejected file shapes (gif, svg, png-name-with-wrong-content-type, pdf,
no extension); png/jpg/jpeg/uppercase accepted; >2 MB → 422; S3 failure → 502;
no file → 422. Delete: clears the path and deletes the object; no-op with no row;
no-op with no logo; repeatable; **S3 delete failure → 502 with the path left
intact so a retry can finish** — deliberately different from the replace path.

### `/proposal` — `test_proposals.py` (92)

| Group | Cases |
|---|---|
| Requirement docs | proposal + document created and the pipeline runs **inline** (the summary comes back in the same response); multiple files in upload order with `additional_documents`; **auto-naming** from the first parsed `project_title`; auto-naming honours a configured `proposal_naming_template`; an explicit name is never overwritten; attaching to an existing proposal **without overwriting its `client_name`/`title`**; unknown / soft-deleted proposal → 404; no files → 422; blank-filename parts ignored → 422; non-file `files` value → 422; missing `client_name` → 422; S3 failure → 502; **parse failure → 422** |
| Generate (SSE) | streams `section_start` → `section_chunk` → `section_done` → `done` with correct `content-type`, `cache-control` and `x-accel-buffering` headers, and asserts the arguments passed through; unknown / soft-deleted → 404 **and the generator is never invoked**; 4 sub-minimum page counts → 422; 5 validation shapes; `knowledge_augmented` mode |
| Templates / stats | ids match `EXPORT_TEMPLATES` and previews are presigned; **`/templates` not swallowed by `/{proposal_id}`**; stats all-zero when empty; per-status breakdown; soft-deleted excluded |
| List | newest-first pagination; sections and `requirement_document_ids` included; **search spans title *and* `client_name`**; status / `created_by` / `created_from` / `created_to` filters; soft-deleted excluded; empty → 200; unknown status → 422 |
| Status | 4 forward transitions; **4 backward transitions → 409**; same-status allowed; **`failed` settable from any state** (an abort marker, not a pipeline stage); **a failed proposal can move anywhere** (otherwise it is permanently stuck); `done` schedules knowledge re-ingestion; **calling `done` twice re-ingests twice** (deliberate — post-approval edits still reach the KB); a non-`done` target does not; unknown → 404; missing / unknown status param → 422 |
| Export | PDF and DOCX downloads with correct content type and `Content-Disposition` filename; **marks the proposal DONE**; no sections → 409; unknown template → 404; unknown proposal → 404; render failure → 502; unknown / missing format → 422 |
| Email export | sends and confirms; **the binary is not returned**; send failure → 502; invalid address → 422; **no sections → 409 and no mail sent** |

Contains **[bug 3](#bug-3--export-returns-an-opaque-500-when-pandoc-is-unavailable)** (xfail).

### Wizard endpoints — `test_proposal_wizard.py` (23)

The generation-wizard endpoints on `router/proposals.py` —
`GET /proposal/{proposal_id}/state` and `GET`/`PATCH
/proposal/{proposal_id}/sections`. These used to live in a separate unprefixed
`router/proposal_temp.py`, which has been folded into the proposals router.

Step progression `proposal_details` → `summary` → `generation_config` →
`generation`; `review` and `done` both collapse to `"done"`; `failed` reported;
**multi-file aggregation** — summaries concatenated under per-file headings,
matches and capability tags de-duplicated keeping the strongest score per
knowledge document / tag name (the case where reading only the newest document
hid every earlier upload); 404s; auth.

Sections: ordered retrieval; empty for an ungenerated proposal; reorder;
**sections omitted from the payload are deleted**; an empty list clears
everything; a section from another proposal → 400; unknown id → 400; **a
partially-valid payload leaves `order_index` untouched** (the ownership check runs
over the whole payload before any delete); 404 and 422 shapes.

### Generation pipeline — `test_generation_pipeline.py` (49)

The only place the real drafting pipeline runs. Everything is real except
`GroqChatClient.stream_complete`, which is replaced by a fake that answers any
section — the LangGraph run, the SSE framing, the token budgeting and the DB
writes are all live, which is what makes "twelve rows persisted" and "never more
than three in flight" mean anything.

These exist because of a bug that shipped silently. `gpt-oss` streams reasoning
tokens on a separate delta field, billed against the same allowance as the visible
draft; `stream_complete` read only `delta.content` and never checked
`finish_reason`, so a response that reasoned until it ran out of room persisted as
a **finished-but-empty section**. The fake therefore populates `StreamOutcome`
exactly as the real client does — a fake that left `finish_reason` unset would
fail every section as truncated.

*Token budgeting:* caps scale with the word target and never fall below the floor;
the clamp keeps the whole request under the per-request ceiling **whenever the
prompt leaves room**, and `prompt_exceeds_ceiling` flags the case where no cap can
help (that one is sent anyway — Groq's tokenizer is the authority and the local
estimate can be pessimistic).

*Rate limiting:* Groq's duration formats (`952ms`, `1.492s`, `1m26.4s`) parse; the
governor **learns the real limit from `x-ratelimit-limit-tokens`** and overrides
config; it debits locally so concurrent sections see a reservation before the
header arrives; it lets the very first request of a process through rather than
stalling on a guess; a 429 **waits exactly the `Retry-After` value** rather than a
backoff curve of our own; a **413 is not retried at all** and its message names
`page_count` and `tokens_per_minute`.

*The previously-silent failures:* empty content raises and **the error names
`reasoning_effort`** (nothing in an empty stream hints at the cause); whitespace-only
counts as empty; truncation raises **even though text arrived**; an absent
`finish_reason` is treated as a dropped tail, not a clean finish; Groq's usage-only
trailer (`choices: []`) is skipped rather than raising `IndexError`.

*Contract preservation:* every non-generation caller still sends a byte-identical
request (`max_completion_tokens` and `reasoning_effort` omitted when unset,
`temperature=0.4`, no tool calling); one `stream_complete` per section with no
batching; SSE event names and `section_start`/`section_done` payloads unchanged;
`section_chunk` carries `content` **plus** the added `name`; streamed chunks
reassemble to the stored content; proposal ends `REVIEW` with markdown uploaded.

*Concurrency:* the default of 1 reproduces strictly sequential drafting;
`GENERATION_CONCURRENCY` overrides config and ignores garbage and `0`; the
semaphore is never exceeded and genuinely overlaps above 1; out-of-order
completion still persists the correct `order_index`; a failing section marks the
proposal `FAILED` and emits `error` with **no `done`**, while sections that already
completed stay persisted.

One fixture is worth knowing about: `serialized_db_sessions`. conftest pins every
session to a single SQLite `:memory:` connection via `StaticPool`, and two
concurrent transactions on one connection fail with *"cannot commit transaction -
SQL statements in progress"*. Production is Postgres with a 10+20 pool, so each
concurrent section gets its own connection and `proposal_sections` has no unique
constraint to contend over. The fixture serializes only the DB blocks, so drafting
still overlaps and the concurrency assertions stay meaningful — **it is the
fixture's constraint, not the pipeline's**.

### Cross-cutting — `test_middleware.py` (13)

Root needs no auth; unknown path → 404; wrong method → 405; **an unexpected
exception becomes a clean 500 with no traceback and no internal message leaked**;
`SQLAlchemyError` → 503; **deliberate `HTTPException`s keep their status and
detail** rather than being flattened to 500; CORS preflight; CORS headers on a
normal response; **CORS headers survive an error response** (CORS is registered
outermost precisely so the browser doesn't hide the error); 3 static paths not
captured by sibling dynamic routes; **`/openapi.json` builds** — which is what
catches a `response_model` mismatch or a duplicate operation id.

### Primitives — `test_hash.py` (21)

This file previously was a print-based script importing a nonexistent
`authentication.hash` module, so it **errored during collection**. Rewritten as
real tests.

Hashing: plaintext not stored; bcrypt prefix; verify accepts and rejects;
**salted** (two hashes differ, both verify); 5 edge-case passwords (empty, space,
single char, unicode, 60 chars); case-sensitive; **bcrypt's 72-byte truncation**
pinned as a documented property rather than a bug.

JWT: access and reset tokens round-trip; refresh and reset tokens rejected as
access tokens; garbage; foreign signature; wrong issuer; expired; a reset token
created already-expired is unusable.

---

## 9. Why 3 tests "fail"

**They don't.** The suite exits **0**.

Those three are marked `@pytest.mark.xfail(strict=True)` — pytest's mechanism for
"this test asserts the correct behaviour, the code does not do that yet, and
that is known". In the progress output `.` is a pass, `x` is an xfail and `F` is
a real failure. There are no `F`s.

`strict=True` matters: if someone fixes the underlying bug, the test starts
passing, and pytest reports **XPASS as a failure**, forcing the marker to be
removed. Each one is a tripwire, not swept-under-the-rug breakage.

```bash
pytest -rx           # show the reasons
pytest --runxfail    # run them for real → 3 failures, showing the bugs
```

None of the application code has been modified. Fixing these is a product
decision.

---

### Bug 1 — every self-registered user becomes `org_admin`

**Test:** `test_auth.py::test_register_honours_the_requested_role`
**Severity:** high — this is a privilege-escalation path.

`utilities/generic.py`:

```python
def assign_role(is_organization_admin: bool) -> UserRole:
    """Centralised role assignment: organisations become admins, individuals become users."""
    return UserRole.ADMIN if is_organization_admin else UserRole.USER
```

The parameter is a **bool**. But `authentication/auth_service.py::register`
passes a `UserRole`:

```python
user = User(
    email=register_request.email,
    hashed_password=hash_password(register_request.password),
    role=assign_role(register_request.role),      # ← register_request.role is a UserRole
    is_first_login=True,
)
```

`UserRole` subclasses `str`, so truthiness is *string* truthiness — and both
`"org_admin"` and `"member"` are non-empty strings. `assign_role` is therefore
**always** truthy and **always** returns `UserRole.ADMIN`.

```
POST /auth/register  {"role": "member"}   →   creates an org_admin
```

`POST /auth/create-user` does it correctly (`role=request.role`), which is why
`test_admin_can_create_a_user` asserts `UserRole.USER` and passes. That contrast
is what localises the bug to `register`.

**Suggested fix:** use `register_request.role` directly in `register`, exactly as
`create_user_by_admin` does. `assign_role` remains correct for a genuine bool
caller. Consider whether self-registration should be able to request `org_admin`
at all.

---

### Bug 2 — renaming a category onto a soft-deleted name returns 503

**Tests:** `test_category.py::test_renaming_onto_a_soft_deleted_name_currently_500s`
(pins today's behaviour, passes) and
`test_renaming_onto_a_soft_deleted_name_should_be_a_client_error` (xfail)
**Severity:** medium — wrong status code, opaque error message.

`Category.name` is `unique=True` at the database level, and deletion is a soft
delete — so a deleted category still occupies its name while being invisible to
`/category/list`.

The **create** branch of `router/category.py` handles this properly: it looks for
the hidden row with `get_category_by_name_including_deleted` and revives it. The
**update** branch does not:

```python
existing_result = await db.execute(
    select(Category).filter(
        Category.name == request.name,
        Category.id != request.id,
        Category.is_active.is_(True),        # ← soft-deleted rows are invisible here
    )
)
existing = existing_result.scalars().first()
if existing:
    raise HTTPException(status_code=400, detail="Category name already exists")

category.name = request.name
category.description = request.description
...
await db.commit()                            # ← IntegrityError: UNIQUE constraint failed
```

The name passes the application-level check, then the database rejects it.
`ErrorHandlerMiddleware` catches `SQLAlchemyError` and returns a generic
**503 "A database error occurred. Please try again."** — which tells the client
nothing about what actually went wrong, and misreports a client error as a server
availability problem.

**Suggested fix:** drop the `is_active` filter from the update branch's duplicate
check (returning the existing 400), or reuse the create branch's
revive-the-hidden-row logic.

---

### Bug 3 — export returns an opaque 500 when pandoc is unavailable

**Tests:** `test_proposals.py::test_export_500s_when_markdown_to_html_conversion_fails`
(pins today's behaviour, passes) and
`test_export_should_502_when_markdown_to_html_conversion_fails` (xfail)
**Severity:** medium — wrong status code on a real operational failure mode.

`services/proposal_export_service.py::render_proposal_document`:

```python
proposal_json = _build_proposal_json(proposal)      # ← unguarded
html = render_proposal_html(                        # ← unguarded, calls pypandoc
    proposal_json, template_id, ...
)

try:
    content = (
        render_pdf_from_html(html)
        if export_format == ExportFormat.PDF
        else render_docx_from_html(html, reference_docx=get_docx_reference_path(template_id))
    )
except Exception:
    logger.exception(...)
    raise HTTPException(status_code=502, detail="Failed to render proposal export")
```

Only the PDF/DOCX step is guarded. But `render_proposal_html` →
`rendering/html_renderer.py::_section_to_html` → `pypandoc.convert_text(...)`
runs **every section's Markdown through the native `pandoc` binary** — even for a
PDF export, where you would expect only WeasyPrint to be involved. If pandoc is
missing or cannot run, that raises *outside* the `try`, and the caller gets a bare
**500 "An unexpected error occurred."** instead of the intended 502.

This is not hypothetical. It is how the bug was found: the export tests initially
stubbed only the PDF/DOCX renderers, passed, then failed on a later run with

```
pandoc.exe: getMBlocks: VirtualAlloc MEM_COMMIT failed:
The paging file is too small for this operation to complete.
```

That was a defect in the *test harness* — a native binary left in the code path,
making results machine-dependent. `stub_renderers` now stubs all three
functions, so the export tests are hermetic. The underlying application gap is
real and remains pinned.

Relevant to deployment: `requirements.txt` notes that pandoc must be installed
separately as a system package (`apt-get install pandoc`) — pip alone is not
enough. On an image that misses it, **every** export returns 500 rather than a
diagnosable 502.

**Suggested fix:** move `render_proposal_html` (and arguably
`_build_proposal_json`) inside the `try`, so any rendering-stage failure produces
the 502 the endpoint already documents.

---

## 10. Writing a new test

### Anatomy

```python
"""One line saying which endpoints this module covers."""

from helpers import auth_headers, upload      # NOT `from test.helpers import ...`


async def test_thing_does_what_it_says(client, member, factory, fake_s3):
    # ARRANGE — build rows through the ORM, not through the API
    category = await factory.category(name="Case Studies")

    # ACT
    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_name": "Study", "category_id": str(category.id)},
        files={"file": upload("study.pdf")},
    )

    # ASSERT — status, body, DB state, side effects
    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert len(fake_s3.uploaded) == 1
```

No `@pytest.mark.asyncio` needed — `asyncio_mode = "auto"` handles it.

### Import rule

Use `from helpers import ...`, **never** `from test.helpers import ...`.

The repo has a top-level `test.py` script *and* a `test/` directory. A regular
module shadows a namespace package, so `import test.anything` resolves to
`test.py` and fails with `'test' is not a package` — and as a side effect
*executes* that script (it performs a DNS lookup). pytest puts `test/` on
`sys.path`, so the bare import is both correct and safe.

### Multipart requests

```python
# single file
files={"file": upload("a.pdf")}
files={"file": ("logo.png", b"\x89PNG", "image/png")}

# repeated field (List[UploadFile])
files=[("files", upload("first.pdf")), ("files", upload("second.pdf"))]

# form fields alongside — all values must be strings
data={"category_id": str(category.id), "tags": ["aws", "migration"]}
```

Note the distinction the suite makes: a part with a **blank filename** reaches
the handler as an `UploadFile` and hits its own "no file" guard, whereas a part
with **no filename at all** arrives as a plain string and is rejected earlier by
Pydantic. Both are 422, via different paths.

### Injecting failures

```python
async def test_s3_down(client, member, factory, fake_s3):
    fake_s3.upload_error = RuntimeError("bucket unreachable")
    ...
    assert response.status_code == 502

async def test_smtp_down(client, admin_headers, monkeypatch):
    import services.team_service as team_service

    async def explode(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(team_service, "send_team_invite_email", explode)
```

Patch the module that **uses** the function, not the one that defines it — the
consumers bind these names at import time.

### Asserting background work

```python
async def test_schedules_ingestion(client, member, factory, stub_background_pipelines):
    proposal = await factory.proposal(user=member, status=ProposalStatus.REVIEW)

    await client.patch(f"/proposal/{proposal.id}/status?status=done", headers=auth_headers(member))

    assert stub_background_pipelines["ingest_proposal_as_knowledge"] == [proposal.id]
```

### Found a bug? Pin it

Don't assert the broken behaviour silently, and don't leave a failing test. Write
both halves:

```python
async def test_x_currently_500s(client, ...):
    """Current behaviour, pinned deliberately — see the xfail below."""
    assert response.status_code == 500


@pytest.mark.xfail(strict=True, reason="BUG: <file:function> does X; it should do Y because Z.")
async def test_x_should_502(client, ...):
    assert response.status_code == 502
```

The reason string is the bug report — make it specific enough to act on.

---

## 11. Troubleshooting and gotchas

| Symptom | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'main'` | `pythonpath = ["."]` missing from `pyproject.toml`, or pytest invoked from outside the repo root |
| `'test' is not a package`, and a stray IP address printed during collection | Something did `from test.X import ...`; the top-level `test.py` shadowed the directory *and* ran. Use `from helpers import ...` |
| `RuntimeError: CONFIG environment variable is required` | An app module got imported before `conftest.py` set `CONFIG`. Keep the `os.environ["CONFIG"] = ...` assignment as the first statement, above every app import |
| `no such table: users` | The `engine` fixture wasn't used (directly or transitively). Request `client`, `db` or `factory` |
| Tests pass individually but fail together, or vice versa | Each test gets a brand-new database, so this points at module-level state rather than data. Every module is verified to pass standalone |
| A test hits a real service | Add the call site to an autouse stub in `conftest.py`. Patch where the function is **used** |
| Export tests fail with pandoc errors | `stub_renderers` wasn't requested, or a test overrode a renderer without requesting it first. See `test_export_502s_when_rendering_blows_up` for the correct ordering |
| Suite suddenly takes ~2 minutes | The bcrypt rounds override in `conftest.py` was removed |
| `StarletteDeprecationWarning: HTTP_422_UNPROCESSABLE_ENTITY` | Pre-existing in FastAPI and in `services/organization_settings_service.py`. Cosmetic; unrelated to the tests |

### Deliberate design decisions worth not "fixing"

- **Function-scoped `engine`.** Slower in principle, but it removes all
  cross-test data leakage and every truncate/rollback helper. SQLite table
  creation is sub-millisecond; it does not show up in the run time.
- **`StaticPool`.** Not an optimisation — without it, `:memory:` gives each
  connection its own empty database and the arrange session becomes invisible to
  the request.
- **Auth not overridden.** Slightly more setup per test, and the reason the
  token-handling tests mean anything.
- **`bcrypt__default_rounds=4`.** The only place a security parameter is weakened,
  and it is confined to the test process. The real code path still runs.
- **Autouse stubs.** They make it impossible to *forget* to stub something. A
  test that needs to observe or break one just requests it by name.
