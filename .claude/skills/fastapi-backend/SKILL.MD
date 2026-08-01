---
name: fastapi-backend
description: Use when creating or modifying FastAPI routers, endpoints, request/response schemas, dependencies, background tasks, or streaming responses in the Proposal AI backend.
---

# FastAPI Backend Skill

## Purpose

This skill governs router/endpoint design, request/response schemas, dependency injection, background work, and streaming responses across the Proposal AI backend.

Tech stack

- FastAPI
- Pydantic v2 (request/response schemas)
- SQLAlchemy 2.x Async ORM + AsyncPG (see the `database` skill for model/migration rules)
- JWT auth via `authentication/`

For a full narrative of how the existing routers/pipelines actually behave today (including what's live vs. dead code), see the `system-workflow` skill — this file is about how to build correctly, not what already exists.

---

# Router Organization

- One router per domain (`router/documents.py`, `router/proposals.py`, `router/category.py`, `router/auth_router.py`, etc.), mounted in `main.py` via `app.include_router(...)` with an explicit `prefix` and `tags`.
- Do not create a second parallel router for the same resource "temporarily" (this repo already has `router/proposal_temp.py` alongside `router/proposals.py`, which has caused endpoint drift — e.g. regenerate/approve routes existing in one but not the other at different points in time). If a route is genuinely temporary, mark it clearly (docstring + tag) and plan its removal; better yet, add it to the real router.
- Register more specific/static paths (`GET /proposals/templates`, `GET /proposals/stats`) before parameterized paths (`GET /proposals/{proposal_id}`) to avoid path-matching collisions.

---

# Auth

- Every authenticated route takes `current_user: dict = Depends(get_current_user)` (`authentication/dependency.py`).
- Never trust a `user_id` passed in the request body/query for identity — always derive it from `current_user`.

---

# Request/Response Schemas

- Every endpoint should declare an explicit Pydantic response schema (`schemas/*.py`) — never return ORM model instances directly.
- Keep request schemas separate from response schemas even when similar; don't reuse a response model as a request body.
- Multipart file uploads: accept `file: UploadFile` alongside plain form fields (see `router/documents.py`, `router/proposals.py`), not a JSON body — file + metadata always travel together as multipart form data in this codebase.
- Prefer flattening related data into one response (e.g. `_requirement_document_response` merges document + parent-proposal fields) over exposing a nested/joined shape when the client only ever consumes it flattened.

---

# Database Sessions

- Request-scoped: `db: AsyncSession = Depends(get_db)` — use for anything that must finish before the response returns.
- Background-task-scoped: `async with db_session():` (`database/database.py`) — use inside anything that runs *after* the request handler returns (a `BackgroundTasks` callback, an Arq job body). **Never reuse the request-scoped session inside background code** — it will already be closed by the time the task runs. Every background pipeline function in this repo (`process_knowledge_document`, `process_requirement_document`) opens its own session this way.

---

# Background Work

- The current live pattern for fire-and-forget work is FastAPI's `BackgroundTasks.add_task(...)`, scheduled from inside the route handler, added *after* the triggering DB row is committed.
- Arq infrastructure exists (`tasks/arq_worker.py`, `tasks/arq_pool.py`) but `get_arq_pool()` currently returns a no-op pool — nothing enqueued via `enqueue_job(...)` will actually run. Before adding a new call to `enqueue_job`, either confirm Arq has been reactivated (real `create_pool` uncommented, a worker process running) or use `BackgroundTasks` instead to stay consistent with what currently works. Don't add a call that silently does nothing.
- If a pipeline can fail expensively (LLM calls, OCR, S3), wrap it in `try/except` that sets a terminal `FAILED`-style status, and use `finally` to clean up any temp files — this is the standard shape used by both `process_knowledge_document` and `process_requirement_document_pipeline`.

---

# Streaming Responses (SSE)

- Used for long-running, incrementally-producible work (proposal generation). Pattern (`router/proposals.py:209-235`, `generation/proposal_generator.py`):
  - `StreamingResponse(generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`
  - The generator yields serialized event dicts with a `type`/`name` discriminant (`section_start`, `section_chunk`, `section_done`, `error`, `done`) so the client can distinguish event kinds without a separate SSE `event:` field.
  - On failure mid-stream: persist the failure state (e.g. `status=FAILED`, `error_message=...`) *and* yield an `error` event before returning — don't let the connection just drop silently.

---

# Error Handling

Use `HTTPException` with a status code that matches the actual failure mode — don't default everything to 400/500:

- `404` — resource not found / not owned by an active record
- `409` — invalid state transition (e.g. attempting to move a status backward) or a precondition not met (e.g. exporting a proposal with zero sections)
- `422` — a background pipeline ran but ended in a failure state (e.g. requirement parsing failed)
- `502` — an upstream dependency failed (S3 upload/download, SMTP send, LLM call) — this is not the caller's fault

Never swallow an exception silently — log it (`utilities/logger.py`) before converting it to an `HTTPException` or a stored `FAILED` status.

---

# File Upload Conventions

1. Derive `extension` from the filename (`Path(filename).suffix.lstrip(".").lower()`).
2. Build the S3 key via `S3PathBuilder` (`utilities/s3_service.py`) — one method per resource type (`knowledge_document`, `requirement_document`, `proposal_docx`, `proposal_pdf`).
3. Upload to S3 **first**. Only create/update the DB row after the upload succeeds — never leave a DB row pointing at an S3 object that doesn't exist.
4. If replacing a file on an existing row, delete the **old** S3 object only after the new upload has succeeded, and bump any version counter.

For read access: use a presigned URL (`s3_service.generate_presigned_url`, default 1-hour expiry) for inline/preview access; use a streamed download route (read bytes server-side, return with `Content-Disposition: attachment`) when the client expects a direct file download through the API rather than a redirect.

---

# Soft Delete & Status Fields

- Every model extends `BasicModel` (`id`, `is_active`, `created_at`, `updated_at`) — deletion is `is_active = False`, never a hard `DELETE`. Every list/get query must filter `is_active.is_(True)`.
- When a resource has a deletion path, check whether deleting it should also clean up dependent state in other systems (vector store entries, child rows) — don't assume a soft-delete alone is enough; this repo currently has at least one gap where a knowledge-document delete does not clean up its Pinecone vectors/chunks (see `system-workflow`'s knowledge-flow reference).
- For any resource with a multi-stage status enum (`ProposalStatus`, `DocumentStatus`, `IngestionStatus`), prefer the forward-only rank-checked transition pattern already used by `set_proposal_status` over allowing arbitrary status writes, unless the resource genuinely needs bidirectional transitions.

---

# Before Completing Any Endpoint

Verify

✓ Explicit request and response schemas

✓ Auth dependency present, identity taken from `current_user`

✓ Correct DB session type for where the code runs (request vs. background)

✓ File uploads: S3 write before DB write, old file cleanup on replace

✓ Correct HTTP status codes for each failure mode

✓ Soft-delete / `is_active` filtering applied to all reads

✓ Background work uses a pattern that actually runs (not a no-op `enqueue_job`)

✓ No duplicate/parallel router for the same resource

If any item is missing, the endpoint is not complete.
