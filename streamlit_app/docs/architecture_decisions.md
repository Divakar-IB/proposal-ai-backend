# Architecture Decisions

## Why Streamlit

The brief specified it, and it fits: this is an internal tool for reviewing/refining LLM output,
not a public-facing product. Streamlit's session-state + rerun model maps cleanly onto a linear
wizard (upload → processing → review → export) without needing a separate frontend build
pipeline, router, or API layer of its own — the whole app is Python calling the existing FastAPI
backend directly.

## Why the existing backend was reused, not rewritten

The backend already had a working, tested pipeline (extraction → requirement parsing →
capability classification → knowledge matching → LangGraph section generation with
quality-check/retry logic). Duplicating any of that in the frontend would mean two sources of
truth for business logic that's inherently backend-shaped (LLM calls, Pinecone queries, S3
uploads, DB transactions). The frontend's job is presentation and orchestration of *existing*
calls, nothing more. Concretely:

- `services/api_client.py` contains zero business logic — every method is a thin HTTP call plus
  error normalization. No retry/backoff policy re-implements anything the backend already does
  (e.g. section retry-on-low-confidence stays entirely server-side).
- The two backend additions (`GET /proposals`, `parsed_requirements` on
  `RequirementDocumentResponse`) are strictly additive — new endpoint/field, zero changes to
  existing signatures, logic, or migrations. Both follow patterns already established in the
  codebase (`build_knowledge_documents_query`/`DocumentListResponse` for the former; the column
  already existed and was already computed, just never returned, for the latter).

## `pages/` → `views/` rename

Streamlit auto-discovers *any* directory named `pages/` next to the entry script and turns each
`.py` file inside it into a native sidebar navigation entry — regardless of an `__init__.py`.
That would have put the "hidden" Step 2 processing page directly in the nav, which the brief
explicitly rules out ("This page is NOT visible"). The workflow views therefore live in
`views/`, and `app.py` dispatches to them explicitly based on `st.session_state.workflow_stage` —
giving full control over which stages are ever reachable, and letting the custom sidebar (not
Streamlit's default page list) own navigation entirely.

## Single-file-per-proposal upload, not true multi-file RFP intake

The backend's data model is 1:1 — `Proposal.requirement_document_id` is a single foreign key, and
`POST /proposals/requirement-documents` accepts exactly one `file`. The brief's Step 1 asks for
"one or more" documents. Rather than silently dropping extra files or inventing a fake multi-file
backend call, the upload page:

- accepts multiple files in the picker (for a smoother drag-and-drop experience and future-proofing),
- validates all of them,
- and explicitly tells the user only the first valid one will be processed if more than one is
  present.

Building real multi-document consolidation (merging several RFPs' requirements into one parsed
schema) is a pipeline change, not a wiring exercise — it would need new logic in
`requirements_parsing/`, not just a frontend change, so it's out of scope here and called out as
a future enhancement instead of quietly faked.

## Token/cost optimization strategy

The frontend doesn't add any LLM calls of its own — every Groq/embedding call already happens
exactly once, server-side, in the existing pipeline. The frontend's contribution to cost control
is entirely about *not triggering extra backend work*:

- **Regenerate is per-section, not per-proposal.** `POST /proposals/sections/{id}/regenerate`
  reruns exactly one section's draft + quality-check pass, reusing the proposal's existing
  `category_ids` scope — a user fixing one weak section never re-drafts the other 13.
- **Manual edits bypass the LLM entirely.** `PATCH /proposals/sections/{id}` is a plain content
  overwrite; a reviewer who just wants to fix a typo or reword a sentence never needs to spend a
  regeneration call to do it.
- **The SSE stream is consumed once per generation run**, with a session-state guard
  (`generation_running_for`/`generation_done_for`) preventing an accidental duplicate call to
  `POST /proposals/generate` if the processing page's script were to rerun mid-stream.
- **The system-health check is cached** (`st.cache_data(ttl=20)`) rather than pinging the backend
  on every single rerun the sidebar triggers.

## Known limitation: synchronous SSE consumption

`generate_proposal()` is consumed as a plain Python generator inside the Streamlit script's main
thread — this is simple and correct for the common case, but a script rerun mid-stream (e.g. a
browser reconnect) would need to restart consumption from the top rather than resuming. Given the
backend's generation graph itself isn't fully idempotent to interrupt (it's driving live LLM
calls), a more robust version would move stream consumption to a background thread writing into a
queue the Streamlit script polls — flagged as a future enhancement in developer_handover.md rather
than built now, to keep this pass focused on wiring the real workflow end-to-end first.
