# Workflow Documentation

## End-to-end workflow

1. **Login** — `components/login.py` gates the whole app. `services/auth.login()` calls
   `POST /auth/login`, stores `access_token`/`refresh_token`/`role` in `st.session_state`.

2. **Step 1 — Upload Requirements** (`views/upload.py`)
   - User uploads one or more files (UI accepts multiple for convenience; only the first valid
     one is submitted — see [architecture_decisions.md](architecture_decisions.md) for why),
     enters Proposal Name, Client Name, and an optional Proposal Description.
   - On **Continue**, calls `POST /proposals/requirement-documents` with the file plus form
     fields. This one call is synchronous and already runs the entire hidden-processing pipeline
     described below — the response includes the extracted summary, capability tags, and
     knowledge-base matches immediately.
   - Response is stored in `st.session_state.requirement_document`; `proposal_id` is read from
     `response["proposal_id"]`. `workflow_stage` moves to `"processing"`.

3. **Step 2 — Backend Processing (hidden)** (`views/processing.py`)
   - Never a sidebar/nav destination — reached only via the stage transition above.
   - Everything except proposal generation itself (OCR, requirement extraction, metadata
     extraction, capability classification, knowledge-base matching, context preparation) already
     ran synchronously inside Step 1's upload call. What this page actually drives live is
     **proposal generation**: `POST /proposals/generate`, consumed as Server-Sent Events.
   - The client (`services/api_client.py::generate_proposal`) parses raw `event:`/`data:` lines
     from the streaming response and yields typed `SSEEvent(event, data)` objects. The page loop
     updates a progress bar and a per-section status list as `section` events arrive, shows
     `error` events as recoverable warnings, and on `failed` shows a retry button.
   - On `done`, fetches the full compiled proposal via `GET /proposals/{proposal_id}` and stores
     it in `st.session_state.proposal`, then transitions `workflow_stage` to `"review"`.

4. **Step 3 — Review & Refine** (`views/review.py`)
   - Renders Proposal Summary, Workflow Status, Statistics, Confidence, Requirements Covered,
     Missing Information, Review Flags, and one expandable card per generated section.
   - Each section card has View / Edit / Regenerate / Approve, calling
     `PATCH /proposals/sections/{id}`, `POST /proposals/sections/{id}/regenerate`, and
     `POST /proposals/sections/{id}/approve` respectively. Every action updates the section
     in-place in `st.session_state.proposal["sections"]` and reruns.
   - "Requirements Covered" and "Missing Information" are derived from
     `requirement_document.parsed_requirements` (technical requirements / deliverables listed;
     optional fields like budget range or timeline flagged if the source RFP didn't specify them)
     — see architecture_decisions.md for why this field was added to the backend response.

5. **Step 4 — Export** (`views/export.py`) — UI-only placeholder; no backend export endpoints
   exist yet. Buttons are visibly disabled with a "Coming soon" caption rather than silently doing
   nothing.

6. **Dashboard** (`views/dashboard.py`) — reachable any time via the sidebar. Lists proposals via
   the new `GET /proposals` endpoint, with client-name search and status filter. Opening a
   proposal re-fetches both the `ProposalResponse` and its `RequirementDocumentResponse` and jumps
   straight to Review & Refine.

## Backend interactions (by page)

| Page | Backend calls |
|---|---|
| Login | `POST /auth/login`, (silently) `POST /auth/refresh` on 401 |
| Upload | `POST /proposals/requirement-documents` |
| Processing | `POST /proposals/generate` (SSE), then `GET /proposals/{id}` |
| Review & Refine | `PATCH /proposals/sections/{id}`, `POST /proposals/sections/{id}/regenerate`, `POST /proposals/sections/{id}/approve` |
| Export | none (placeholder) |
| Dashboard | `GET /proposals`, `GET /proposals/{id}`, `GET /proposals/requirement-documents/{id}` |
| Sidebar (always) | `GET /` (health check, cached 20s) |

## Hidden processing flow, precisely

The spec's Step 2 bullet list (OCR, requirement extraction, metadata extraction, capability
classification, knowledge-base matching, context preparation, proposal generation) maps onto the
*actual* backend pipeline as follows:

- OCR / requirement extraction / metadata extraction / capability classification / knowledge-base
  matching / context preparation → all inside `tasks/requirement_processing.py::process_requirement_document_pipeline`,
  called **synchronously** by `POST /proposals/requirement-documents`. From the frontend's point of
  view this is a single blocking call, shown as a spinner during Step 1's "Continue" click.
- Proposal generation (draft → quality-check → revise, per section) → the LangGraph pipeline in
  `generation/graph.py` / `generation/nodes.py`, driven by `POST /proposals/generate` and streamed
  as SSE. This is what Step 2's live progress UI actually shows.

## Proposal generation flow (what the SSE stream represents)

For each of the 14 fixed sections (`generation/sections.py::SECTION_DEFINITIONS`):
1. Retrieve relevant knowledge-base chunks scoped by the proposal's `category_ids`.
2. Draft the section via Groq.
3. Quality-check the draft; sections scoring below the confidence threshold (0.7) are flagged for
   review (`review_flag=True`) even once approved, and low-confidence/failed checks trigger up to
   2 retries before being force-approved.
4. Emit a `section` SSE event with the section's current `{key, title, status, content, sources,
   confidence_score, review_flag}` every time this fingerprint changes.

Once every section settles, the graph's `compile_proposal` node persists all `ProposalSection`
rows, uploads a compiled markdown file to S3, and sets the final `Proposal.status` — then the
stream emits `done`.
