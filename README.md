# Proposal AI Backend

## Overview

Proposal AI is a FastAPI backend that turns an RFP/requirement document into a draft proposal. Users upload knowledge-base documents (past case studies, capability statements, pricing sheets, etc.) and requirement documents (RFPs); the system extracts and chunks the former into a Pinecone vector index, parses the latter into structured requirements via an LLM, and then runs a LangGraph pipeline that retrieves relevant knowledge chunks per proposal section, drafts each section, quality-checks it, and revises until approved — streaming progress back to the client over Server-Sent Events.

## Features

- JWT-based authentication (register/login/refresh) with role-based access control (`org_admin`, `member`) and forgot/reset password via email (SMTP)
- Knowledge-document upload to S3 with category tagging, versioning, availability status, and presigned download URLs
- Multi-format document extraction (PDF, DOCX, images, Markdown), with OCR fallback for scanned pages
- Markdown-aware chunking and embedding of knowledge documents into a Pinecone vector index
- Structured requirement extraction from RFP documents via an LLM (Groq), including a category knowledge-match score
- LangGraph-driven proposal generation: retrieve → draft → quality-check → revise → compile, streamed as SSE
- Category management with per-category knowledge document counts

## Tech Stack

- **Framework:** FastAPI, Uvicorn
- **Database:** PostgreSQL via SQLAlchemy (async, `asyncpg`) + Alembic migrations
- **Auth:** python-jose (JWT), passlib/bcrypt
- **Storage:** AWS S3 (via boto3)
- **Vector store:** Pinecone
- **LLM:** Groq (OpenAI-compatible chat completions)
- **Embeddings:** Hugging Face Inference API (feature-extraction endpoint)
- **Orchestration:** LangGraph
- **Document processing:** PyMuPDF, python-docx, PaddleOCR, langchain-text-splitters, tiktoken
- **Background jobs:** arq (dependency present; no worker is wired up yet — see [Troubleshooting](#troubleshooting))

## Project Structure

```
.
├── main.py                     # FastAPI app, lifespan (creates DB tables), router registration
├── config.py                   # Pydantic settings, loaded from a single CONFIG env var (JSON)
├── constants.py                # Seed data for knowledge categories
├── alembic/                    # DB migrations
├── authentication/              # JWT, password hashing, auth service, route dependencies
├── router/                     # API routes: auth, category, documents, proposals
├── schemas/                    # Pydantic request/response models
├── database/                   # SQLAlchemy models, session/engine, CRUD, enums
├── extraction/                 # Per-format document extractors (PDF/DOCX/image/Markdown) + OCR
├── chunking/                   # Markdown-aware + recursive text splitting for knowledge chunks
├── embedding/                  # HF Inference embedding client
├── vectorstore/                # Pinecone client, index management, knowledge chunk queries
├── llm/                        # Groq chat-completions client
├── requirements_parsing/       # LLM-driven structured requirement extraction + summary
├── generation/                 # LangGraph nodes/graph/state/prompts for proposal drafting
├── tasks/                      # Document processing / proposal generation orchestration
├── utilities/                  # S3 service, email service, logger, pagination, helpers
├── middleware/                 # CORS, error handling
└── test/                       # Tests
```

## Prerequisites

- Python 3.12+
- PostgreSQL
- AWS S3 bucket + credentials
- Pinecone account/index
- Groq API key
- Hugging Face Inference API token (feature-extraction endpoint)
- SMTP credentials (for forgot/reset password emails)

## Installation

```bash
git clone <repository-url>
cd APG
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

## Environment Variables

Configuration is loaded from a single `CONFIG` environment variable containing a JSON object (see `config.py`), typically set via a `.env` file:

```env
CONFIG='{
  "database": {"username": "...", "password": "...", "host": "...", "port": 5432, "db_name": "...", "pool_size": 10, "max_overflow": 20, "pool_recycle": 1800, "pool_timeout": 30},
  "jwt": {"secret_key": "...", "algorithm": "HS256", "access_token_expire_minutes": 60, "refresh_token_expire_days": 7, "issuer": "proposal-ai"},
  "aws": {"access_key_id": "...", "secret_access_key": "...", "region": "...", "bucket_name": "..."},
  "pinecone": {"api_key": "...", "index_name": "...", "dimension": 1024, "metric": "cosine", "cloud": "aws", "region": "us-east-1"},
  "groq": {"api_key": "...", "base_url": "https://api.groq.com/openai/v1", "llm_model": "openai/gpt-oss-120b"},
  "hf_inference": {"api_token": "...", "embedding_model": "...", "hf_base_api_url": "..."},
  "smtp": {"host": "smtp.gmail.com", "port": 587, "username": "...", "password": "...", "from_email": "...", "use_tls": true},
  "redis": {"host": "localhost", "port": 6379, "db": 0},
  "allowed_origins": ["http://localhost:3000"]
}'
```

`redis` is optional and defaults as shown above; every other top-level key is required at startup. Never commit real credentials — keep `.env` out of version control.

## Configuration

`config.py` reads and parses the `CONFIG` JSON via a Pydantic `BaseSettings` model at import time; a missing or invalid `CONFIG` value raises immediately on startup. `python-dotenv` loads `.env` automatically, so no extra setup is needed beyond having the file present.

## Database Setup

Alembic is configured against a synchronous (`psycopg2`) URL derived from the same database credentials used by the app (see `alembic/env.py`).

```bash
alembic upgrade head          # apply migrations
alembic revision --autogenerate -m "message"   # generate a new migration
```

In addition, `main.py`'s FastAPI lifespan calls `Base.metadata.create_all(checkfirst=True)` on startup, so any model without a corresponding migration is still created — Alembic remains the source of truth for schema changes going forward.

## Running the Project

```bash
uvicorn main:app --reload
```

The API is served at `http://localhost:8000` by default.

## API Documentation

Interactive OpenAPI docs are available once the server is running:

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Key Components

- **`main.py`** — app factory, CORS/error middleware setup, DB table creation on startup, router mounting.
- **`router/auth_router.py`** — register, login, refresh, forgot/reset password, admin user creation.
- **`router/category.py`** — create/update and list knowledge categories with document counts.
- **`router/documents.py`** — upload/list/download/delete knowledge documents (S3 + extraction + chunking + Pinecone indexing).
- **`router/proposals.py`** — upload requirement documents, trigger proposal generation (SSE stream), fetch proposals.
- **`extraction/factory.py`** — dispatches to the correct extractor (PDF, DOCX, image, Markdown) by file extension.
- **`chunking/`** — splits extracted Markdown into embeddable chunks.
- **`vectorstore/`** — Pinecone index management and similarity queries scoped by category.
- **`requirements_parsing/parser.py`** — LLM tool-calling extraction of structured requirements from an RFP, with schema-validation repair retries.
- **`generation/graph.py`** — LangGraph state machine: `parse_requirements → retrieve_context → draft_section ⇄ quality_check → compile_proposal`, with SSE streaming of per-section progress.
- **`utilities/s3_service.py`** — upload/download/copy/move/delete/presigned-URL helpers around a single S3 bucket, with a path-builder for consistent key layout.

## Development Workflow

1. Activate the virtualenv and ensure `CONFIG` is set (e.g. via `.env`).
2. Apply migrations: `alembic upgrade head`.
3. Run the server with `--reload` for local development.
4. Add new tables/columns to `database/models.py`, then generate and apply an Alembic migration.
5. New document formats: add an extractor implementing `BaseExtractor` in `extraction/` and register it in `extraction/factory.py`.
6. New proposal sections: extend `generation/sections.py` (`SECTION_DEFINITIONS`).

## Common Commands

```bash
uvicorn main:app --reload                          # run the dev server
alembic upgrade head                                # apply migrations
alembic revision --autogenerate -m "message"        # create a migration
alembic downgrade -1                                # roll back one migration
pytest                                              # run tests
```

## Troubleshooting

- **`CONFIG environment variable is required...` on startup** — the `CONFIG` env var is missing/unset or not valid JSON; check `.env` is present and loaded.
- **Pydantic validation error on startup** — the `CONFIG` JSON is missing a required key for one of the config sections in `config.py` (e.g. `groq`, `hf_inference`, `smtp`); every section without a default must be present.
- **S3 `AccessDenied` on upload** — the IAM user behind `aws.access_key_id` lacks `s3:PutObject` (and `kms:GenerateDataKey` if the bucket uses SSE-KMS) on the configured bucket; check the IAM policy and bucket policy.
- **Proposal generation stuck/erroring** — check the SSE `error`/`failed` event payload; it surfaces the underlying LangGraph node failure (e.g. Groq/HF Inference/Pinecone errors).
- **Background jobs** — code comments reference "Arq job" background processing, but no Arq worker entry point currently exists in the repo; document and proposal processing currently run inline within the request/response cycle (proposal generation via SSE, document processing synchronously on upload).

## Future Improvements

- Wire up an actual Arq worker/pool for background document and proposal processing (dependency is present but unused).
- Re-enable/complete the `/auth/logout` endpoint (currently commented out).
- Populate the empty `RAG/chunking.py` and `RAG/retriever.py` placeholders or remove them if superseded by `chunking/`/`vectorstore/`.
