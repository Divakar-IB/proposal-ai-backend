# Developer Handover

## Folder structure

```
streamlit_app/
├── app.py                # entry point + workflow-stage router
├── views/                # one module per workflow screen (NOT Streamlit's native pages/ — see architecture_decisions.md)
│   ├── upload.py          # Step 1
│   ├── processing.py      # Step 2 (hidden)
│   ├── review.py          # Step 3
│   ├── export.py          # Step 4 (placeholder)
│   └── dashboard.py
├── components/
│   ├── login.py           # login gate
│   └── sidebar.py         # workflow tracker, project info, progress, activity log, health check
├── services/
│   ├── api_client.py      # Streamlit-agnostic HTTP client — every backend call lives here
│   └── auth.py            # session-state token management, cached client singleton
├── utils/
│   ├── session.py          # st.session_state defaults
│   ├── formatting.py       # status badges, confidence color/label, relative time
│   ├── activity.py         # sidebar activity log
│   └── styling.py          # injects styles/theme.css
├── styles/theme.css
├── config/settings.py      # API base URL/timeouts, app title/layout
├── docs/                   # this file and its four siblings
├── requirements.txt
└── .env.example
```

## Entry points

- **Run the app**: `cd streamlit_app && streamlit run app.py` (needs the backend running
  separately — default expected at `http://localhost:8000`, override via `API_BASE_URL` in
  `streamlit_app/.env`).
- **Run the backend**: from the repo root, `uvicorn main:app --reload` (unchanged from before this
  work — see the root `README.md`).

## Components

- `components/login.py::render_login_gate()` — call this first in any new entry point; returns
  `False` until authenticated, callers should `st.stop()` in that case.
- `components/sidebar.py::render_sidebar()` — call once per script run, after the login gate.
  Reads `st.session_state.proposal` / `.requirement_document` / `.workflow_stage` to render its
  sections; has no side effects beyond a cached backend health check.

## Services (API surface used)

All in `services/api_client.py::ProposalAPIClient`. Every method raises `APIError(status_code,
detail)` on failure — HTTP errors, timeouts, and connection failures all normalize to this one
type, so every call site needs exactly one `except APIError` clause.

| Method | Backend endpoint |
|---|---|
| `login`, `refresh_access_token` | `POST /auth/login`, `POST /auth/refresh` |
| `upload_requirement_document` | `POST /proposals/requirement-documents` |
| `get_requirement_document` | `GET /proposals/requirement-documents/{id}` |
| `generate_proposal` (generator, SSE) | `POST /proposals/generate` |
| `get_proposal` | `GET /proposals/{id}` |
| `list_proposals` | `GET /proposals` (added this pass) |
| `edit_section`, `regenerate_section`, `approve_section` | `PATCH/POST /proposals/sections/{id}/...` |
| `list_categories` | `GET /category/list` (available, not yet used in any page) |
| `health_check` | `GET /` |

`services/auth.py` wraps token lifecycle: `login()`/`logout()`/`is_authenticated()`/
`access_token()`/`try_refresh_access_token()`. `call_with_refresh(fn, *args, **kwargs)` retries a
single mutating call once after a 401, refreshing the access token first — used for every
non-streaming authenticated call. The streaming call (`generate_proposal`) is *not* wrapped this
way (see architecture_decisions.md) — a 401 there just surfaces as an error with a manual retry
button.

## Pending tasks

1. **Export backend** — no docx/pdf/ppt rendering or email-send endpoints exist. `views/export.py`
   is UI-only by design; wire it up once those endpoints land.
2. **Multi-document RFP intake** — backend model is 1:1 today; see architecture_decisions.md.
3. **Category picker** — `GET /category/list` is already wrapped in the client but not surfaced
   anywhere; Step 1 currently relies entirely on the backend's automatic capability-tag-based
   category resolution. Adding an optional override picker would be a frontend-only change.
4. **Role-based UI** — `current_role()` is already tracked in session state but nothing branches
   on it yet (e.g. hiding admin-only actions from `member` users).
5. **Background SSE consumption** — see the "Known limitation" note in architecture_decisions.md.

## Future roadmap (not started)

- Real download links for `Proposal.markdown_path` once a backend endpoint serves it (today it's
  written to S3 internally but nothing reads it back).
- Pagination controls on the Dashboard beyond the first page (`GET /proposals` already supports
  `page`/`limit`; the UI only requests page 1 today).
- Toast/notification polish for background activity (the sidebar's Recent Activities log is
  session-scoped and resets on logout by design).

## Testing notes for whoever picks this up

This was built and verified in a sandbox with no route to the project's actual Postgres/Pinecone/
Groq-backed environment (the dev DB requires SSL the sandbox couldn't negotiate, and there were no
valid login credentials available). Every page was verified with Streamlit's `AppTest` harness
using mocked `ProposalAPIClient` responses (exercising real widget interactions — clicking Approve,
filling the login form, opening a proposal from the Dashboard — not just static rendering), plus a
real headless-browser pass (Playwright) confirming the login screen renders and that a genuine
connection failure surfaces as a clean `st.error` message rather than a crash. **A live end-to-end
run against the real backend with real credentials has not been done** — do that before shipping.
