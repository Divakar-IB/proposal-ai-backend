# Proposal AI Backend — Project Guide

FastAPI backend that turns an RFP/requirement document into a drafted proposal: users upload
knowledge-base documents (case studies, capability statements, pricing sheets) and requirement
documents (RFPs); the system extracts/chunks the former into Pinecone, parses the latter into
structured requirements via an LLM, drafts a proposal section-by-section (streamed over SSE),
and lets a human edit/export it as PDF/DOCX or email it out.

## Tech stack

- **Framework:** FastAPI, Uvicorn
- **Database:** PostgreSQL via SQLAlchemy 2.x async ORM (`asyncpg`) + Alembic migrations
- **Auth:** JWT (python-jose), passlib/bcrypt, role-based (`org_admin`, `member`)
- **Storage:** AWS S3 (boto3)
- **Vector store:** Pinecone (single index, default namespace, category-scoped via metadata filters)
- **LLM:** Groq (OpenAI-compatible chat completions, `openai/gpt-oss-120b`) via `llm/chat_client.py::GroqChatClient`
- **Embeddings:** Hugging Face Inference API
- **Orchestration:** LangGraph (`generation/graph.py` — proposal generation pipeline)
- **Document processing:** PyMuPDF, python-docx, PaddleOCR, langchain-text-splitters, tiktoken
- **Export:** Jinja2 → WeasyPrint (PDF) / Pypandoc (DOCX)
- **Background jobs:** FastAPI `BackgroundTasks` is what actually runs today. Arq (`tasks/arq_*.py`) is
  present but inert — `get_arq_pool()` returns a no-op pool. Don't wire new work through Arq expecting
  it to run.

## Repo structure

```
router/            API routes (documents, proposals, category, auth, organization_settings)
schemas/           Pydantic request/response models
database/          SQLAlchemy models, session/engine, CRUD (database/crud.py), enums (db_enum.py)
alembic/versions/  DB migrations
extraction/        Per-format extractors (PDF/DOCX/image/Markdown) + OCR — shared by knowledge & requirement flows
chunking/          Markdown-aware + recursive text splitting for knowledge chunks
embedding/         HF Inference embedding client
vectorstore/       Pinecone client, index management, similarity queries
llm/               Groq chat-completions client (GroqChatClient)
requirements_parsing/  LLM-driven structured requirement extraction + summary
generation/        LangGraph proposal-generation pipeline: graph.py (nodes/graph), state.py, sections.py,
                    nodes.py (retrieve/draft/quality-check helpers), prompts.py (mostly dead, see below)
services/          Cross-cutting business logic (proposal_review_service, proposal_export_service,
                    proposal_knowledge_service, citation_service, proposal_naming_service,
                    proposal_wizard_service)
tasks/             Background task entry points (document/requirement processing)
rendering/         Jinja2 templates + PDF/DOCX renderers for export
utilities/         S3 service, email service, logger, pagination, helpers
authentication/    JWT, password hashing, route dependencies
middleware/        CORS, error handling
test/              Tests
```

## Available skills — use before touching these areas

This repo has `.claude/skills/` with detailed, authoritative rulebooks. **Load the relevant skill
before editing in its area** rather than guessing conventions from scratch:

| Skill | Covers |
|---|---|
| `database` | SQLAlchemy models, relationships, enums, Alembic migrations, naming/indexing conventions |
| `fastapi-backend` | Routers, schemas, DB session scoping (request vs. background), SSE streaming, error-code conventions, file upload order |
| `knowledge-ingestion` | Upload → extract → chunk → embed → Pinecone pipeline; idempotency/status rules |
| `proposal-generation` | Section definitions, retrieval, drafting prompts, the LangGraph pipeline, quality-check gate |
| `export-proposals` | Markdown → HTML → PDF/DOCX rendering, templates, email export, pre-export document-quality checklist |
| `system-workflow` | **The map of the whole system** — all 5 flows end-to-end, storage locations (Postgres/S3/Pinecone), enum reference, and a maintained list of what's live vs. dead code. Read this first for any cross-cutting change, onboarding, or "how does X work" question. |

`system-workflow`'s `references/*.md` files have full file:line detail per flow
(`knowledge-flow.md`, `requirement-document-flow.md`, `proposal-generation-flow.md`,
`review-workflow.md`, `export-flow.md`).

## Cross-cutting conventions (condensed — see the skills above for full rules)

- **Soft delete only.** Every model extends `BasicModel` (`id`, `is_active`, `created_at`,
  `updated_at`). Deletion is `is_active = False`; every list/get query must filter
  `is_active.is_(True)`. Deleting a resource with vector-store state (knowledge documents,
  proposal-derived knowledge docs) must also clean up Pinecone vectors + `knowledge_chunks` rows.
- **DB sessions:** request-scoped work uses `db: AsyncSession = Depends(get_db)`; anything running
  *after* the request returns (a `BackgroundTasks` callback, a long-running SSE generator) opens
  its own session via `async with db_session():` — never reuse a request-scoped session there.
- **Identity always comes from `current_user` (`Depends(get_current_user)`)** — never trust a
  `user_id` in the request body/query.
- **Status enums are forward-only** where the resource has a pipeline-like lifecycle
  (`ProposalStatus`, `DocumentStatus`, `IngestionStatus`) — see `set_proposal_status`'s
  rank-checked pattern before allowing arbitrary status writes.
- **A database change is never "just the model"** — every model change needs a matching Alembic
  migration in the same pass.
- **Don't create a second parallel router for the same resource.** This repo has had drift before
  (`router/proposal_temp.py` vs `router/proposals.py`) — the temp router has since been folded
  into `router/proposals.py`; don't reintroduce the pattern.
- Prefer HTTPException codes that match the actual failure: `404` not found, `409` invalid state
  transition, `422` background pipeline landed in a failure state, `502` upstream dependency
  failure (S3/SMTP/LLM) — never default everything to 400/500, and never swallow an exception
  without logging it first.

## Known dead / unwired code — don't assume it runs

(Full, maintained list lives in the `system-workflow` skill; high-signal ones repeated here so
they're not missed even without invoking the skill)

- **Arq/Redis queue is fully wired but inert** — `get_arq_pool()` is a no-op. Everything actually
  runs via `BackgroundTasks` or synchronously in the request.
- **`generation/nodes.py::run_quality_check`/`decide_section_status`** are implemented but not
  called by the live `/proposal/generate` stream — every section is force-approved. The
  quality-check retry loop is an intentional future follow-up, not currently active.
- **`Proposal.proposal_json`, `approved_markdown`, `is_approved`, `pdf_path`** always empty — no
  live code path writes them.
- **`Proposal.category_ids`** is read at retrieval time but never set by any live path, so
  category-scoped retrieval is effectively unfiltered today.
- **Export never persists to S3** — PDF/DOCX bytes are returned/emailed and discarded;
  `S3PathBuilder.proposal_docx`/`proposal_pdf` exist for this but are unused.
- **`rendering/templates.py`** is dead; the live rendering path is `rendering/html_templates.py`.
- **`KnowledgeDocument.availability_status` (INACTIVE) doesn't gate Pinecone retrieval** —
  inactive documents remain retrievable.

Before relying on any function that "looks like" it should be wired up, grep for its actual
callers rather than assuming.

## Common commands

```bash
uvicorn main:app --reload                          # run the dev server
alembic upgrade head                                # apply migrations
alembic revision --autogenerate -m "message"        # create a migration
alembic downgrade -1                                # roll back one migration
pytest                                              # run tests
```

## Tests

`pytest` runs the API suite against the real app on an in-memory SQLite stand-in for
Postgres (`test/conftest.py`). Read **`TESTING.md`** before adding or changing tests —
it covers the fixture set, why the Postgres-only `JSONB`/`ARRAY` columns need
`with_variant`, which outbound calls are stubbed and *where* they must be patched, and
the three `xfail(strict=True)` markers that pin known app bugs. Two rules that bite:
import shared helpers as `from helpers import ...` (never `from test.helpers import ...`
— the root-level `test.py` shadows the package), and patch stubs on the module that
*uses* a function, not the one that defines it.

## Windows dev note

WeasyPrint (PDF export) requires the native GTK3 runtime on Windows (`libgobject-2.0-0` etc.) —
not a pip-installable dependency. If `uvicorn` fails on import with
`OSError: cannot load library 'libgobject-2.0-0'`, install it via
`winget install tschoonj.GTKForWindows` and restart the terminal.
