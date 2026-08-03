# Review & Status Workflow

## 0. Ground-truth scope note

`database/crud.py`, `router/proposals.py`, `schemas/proposal.py`, and `services/proposal_review_service.py` had uncommitted working-tree changes at the time this was written, on top of commit `cffb589` ("remove APPROVED status from ProposalStatus enum and update related logic"). This document reflects the **working-tree state**, which includes a second, later round of changes on top of that commit — see §6. Re-check `git status`/`git diff` on these four files before relying on exact line numbers if time has passed.

## 1. End-to-end workflow (current state)

**Wired-up entry points** (`router/proposals.py`):
- `POST /proposal/requirement-documents` — creates the `Proposal` (`status=INPROGRESS`), see requirement-document-flow.md.
- `POST /proposal/generate` — SSE generation stream, see proposal-generation-flow.md.
- `PATCH /proposal/{proposal_id}/sections` — bulk manual edit of section `content` → `services/proposal_review_service.py::edit_sections`. Leaves `status`/`review_flag` untouched by design.
- `PATCH /proposal/{proposal_id}/status` — manual proposal-status override, forward-only → `set_proposal_status`.
- `GET /proposal/stats`, `GET /proposal` — dashboard/listing.
- `DELETE /proposal/{proposal_id}` — soft delete (`is_active=False`).
- `POST /proposal/{proposal_id}/export`, `POST /proposal/{proposal_id}/export/email` — render from **live section rows**, explicitly **not gated on approval** (see export-flow.md).

**Defined but with NO router endpoint currently** (orphaned service functions — see §6):
- `services/proposal_review_service.py::approve_section(db, section_id)` — sets one `ProposalSection.status = APPROVED`, `review_flag=False`.
- `services/proposal_review_service.py::regenerate_section(db, section_id)` — re-drafts one section using the full draft → quality-check → decide-status sequence from `generation/nodes.py`.

**What a human reviewer actually does today, per the wired-up routes:**
1. Generation streams sections; each is persisted directly as `APPROVED` with no quality check (see proposal-generation-flow.md §2), then `Proposal.status → REVIEW`.
2. Reviewer edits section `content` via `PATCH /proposal/{id}/sections` — bulk replace by `section_id`, validated to belong to the same proposal, duplicates rejected.
3. Reviewer (or another process) manually moves `Proposal.status` forward via `PATCH /proposal/{id}/status`, typically to `DONE`.
4. Export renders whatever the sections currently contain — it does not check `status`, `is_approved`, or `approved_markdown`.

What's edited: section `content` (Markdown body) per `ProposalSection` row, individually addressable, bulk-editable in one request. No section-title/outline editing endpoint exists.

Persistence gap: `is_approved`, `approved_markdown`, `proposal_json` exist on `Proposal` and are still returned in `ProposalResponse`, but **nothing in the current working tree sets them** — the function that used to (`approve_proposal`, deleted in `cffb589`) snapshotted sections into `approved_markdown`/`proposal_json` and flipped `is_approved=True`. These three columns are now permanently their defaults (`NULL`/`NULL`/`False`) unless a future feature repopulates them.

## 2. `ProposalStatus` — current values and lifecycle

`database/db_enum.py:20-25`:
```python
class ProposalStatus(str, Enum):
    INPROGRESS = "inprogress"
    GENERATING = "generating"
    REVIEW     = "review"
    DONE       = "done"
    FAILED     = "failed"
```
No `APPROVED`. Meanings, per actual code paths:

| Status | Set where | Meaning |
|---|---|---|
| `INPROGRESS` | `router/proposals.py` (Proposal row created on requirement-doc upload) | Default/initial, before generation starts |
| `GENERATING` | `generation/proposal_generator.py` | Section drafting in progress |
| `REVIEW` | `generation/proposal_generator.py`, on successful completion | All sections drafted, markdown assembled to S3, awaiting human review/edits |
| `DONE` | Only via `PATCH /proposal/{id}/status` | Terminal "finished reviewing" marker — no automatic gate on section states required to reach it (also set as a side-effect of export, see export-flow.md §5) |
| `FAILED` | `generation/proposal_generator.py` (exception), or manual override | Error/abort marker |

**Transition rule** (`services/proposal_review_service.py::set_proposal_status`): forward-only through rank `INPROGRESS(0) < GENERATING(1) < REVIEW(2) < DONE(3)`; moving backward raises 409. `FAILED` is exempt from ranking in both directions — always settable, and once `FAILED`, any status can be set from it.

`ProposalSectionStatus` (`PENDING, DRAFTING, DRAFTED, NEEDS_REVISION, APPROVED`) governs individual sections. `DRAFTING`/`DRAFTED` are defined but **never actually assigned** by the current pipeline — the streaming generator writes sections directly as `APPROVED`; `regenerate_section`/`decide_section_status` only ever produce `APPROVED` or `NEEDS_REVISION`.

## 3. Why `APPROVED` was removed, and what replaced it

History (via `git log -p database/db_enum.py`):
- `171ad26` — `ProposalStatus` created with `REVIEW`, `APPROVED`.
- `c1f596b` — `APPROVED` renamed → `DONE` (migration `a92e6f1d4c3b`).
- `9b04d3a` — `APPROVED` **re-added** alongside `DONE` (both existed: `INPROGRESS, GENERATING, REVIEW, APPROVED, DONE, FAILED`). Same commit added `Proposal.is_approved`/`approved_markdown` (migration `e3f4a5b6c7d8`) and built `approve_proposal()` — gated on all sections being `APPROVED` and clear of `review_flag`, snapshotting `approved_markdown`/`proposal_json`, setting `status=APPROVED, is_approved=True`.
- `cffb589` ("feat: remove APPROVED status from ProposalStatus enum and update related logic") — the most recent structural change:
  - Removes `APPROVED` from `ProposalStatus`.
  - New migration `c8b3f2a1d6e9`: `UPDATE proposals SET status = 'DONE' WHERE status = 'APPROVED'`, then rebuilds the Postgres enum type without `APPROVED` (Postgres has no `DROP VALUE`), with a symmetric `downgrade()`.
  - `router/proposals.py`: `POST /{proposal_id}/approve` replaced by `PATCH /{proposal_id}/status`.
  - `services/proposal_review_service.py`: the whole `approve_proposal()` function (gate-check-sections + snapshot-to-JSON + set `is_approved`) is deleted, replaced by the much simpler forward-only `set_proposal_status()`.

**What replaced it:** a single, generic, forward-only manual status field with no section-level gating, no markdown snapshotting, no `is_approved` semantics. Per the migration comment: *"Existing APPROVED proposals collapse into DONE — there's no dedicated 'approved' concept anymore, so DONE is the closest terminal status."* Approval was demoted from a gated business rule to an untracked convention (a human just sets `DONE` when they're satisfied).

**Orphaned columns:** `Proposal.is_approved`, `approved_markdown`, `proposal_json` were left in place on the model and in response schemas but nothing sets them anymore — this looks like leftover schema debt from the removed feature rather than an active field. Don't assume a future feature will repopulate them without checking current code first.

## 4. LLM-assisted review (`prompts/proposal_review.py` / `generation/nodes.py`)

This is a **per-section automated quality-check**, not a whole-proposal approval prompt and not capability matching (capability matching is unrelated — see requirement-document-flow.md §2e).

- `QUALITY_CHECK_SYSTEM_PROMPT` instructs the model to judge one drafted section against: completeness vs. client requirements, tone, unsupported/fabricated claims (with an explicit rule not to penalize missing citations when no knowledge-base context was retrieved for that section), and misuse of `GAP:` lines.
- Output forced via tool call, schema `QualityCheckResult` (`generation/schema.py`): `{approved: bool, feedback: Optional[str], confidence_score: float}`.
- `run_quality_check()` (`generation/nodes.py:110-139`) builds the messages from `QUALITY_CHECK_USER_TEMPLATE` (section title, structured requirements JSON, retrieved-context block, drafted content) and forces the tool call.
- `decide_section_status(result, force_approve=False)` (`:142-158`) maps the verdict to `(status, feedback, review_flag)`.

**Important discrepancy:** `decide_section_status`'s docstring frames `force_approve` as used by "the automated pipeline" to land on a terminal state within "a bounded retry budget" — but the actual `/generate` SSE pipeline **never calls this at all**. The only current caller is `regenerate_section()`, which is single-shot (`force_approve=False` always) — and as of the current working tree, that function has **no router endpoint** (§6). So section-level LLM quality review is effectively unreachable via the API today, even though all the underlying code is present and functional.

## 5. Storage — exact Postgres columns

`Proposal` (`database/models.py`):
- `status` — `SAEnum(ProposalStatus)`, default `INPROGRESS`
- `is_approved` — `Boolean`, default `False` — added by `e3f4a5b6c7d8`; currently unused
- `approved_markdown` — `Text`, nullable — added by `e3f4a5b6c7d8`; currently unused
- `proposal_json` — `JSONB`, nullable — added by `a1b2c3d4e5f6`; currently unused for review purposes
- `category_ids` — `ARRAY(Integer)`, nullable — added by `b6d4e91a2f77`; used only for knowledge-retrieval scope (and, per proposal-generation-flow.md, never actually set)
- `markdown_path`, `docx_path`, `pdf_path`, `error_message` — export/generation artifacts

`ProposalSection` (`database/models.py`):
- `status` — `SAEnum(ProposalSectionStatus)`, default `PENDING`
- `confidence_score` — `Float`, nullable — added by `b6d4e91a2f77`; set only by `regenerate_section` (currently unreachable via API)
- `review_flag` — `Boolean`, default `False` — added by `b6d4e91a2f77`; set by `approve_section`/`regenerate_section` (both currently unreachable via API)
- `retry_count` — `Integer`, default 0
- `content`, `citations`, `section_key`, `title`, `order_index`

`RequirementDocument.capability_tags` — `JSONB`, nullable — added by `b6d4e91a2f77` (the "capability" half of that migration's name); unrelated to proposal approval, populated at ingestion time (see requirement-document-flow.md).

Migration chain relevant to this feature, in order: `f3a1c2d9b7e4` (client_name/context) → `a92e6f1d4c3b` (DRAFT→INPROGRESS, APPROVED→DONE rename) → `b6d4e91a2f77` (capability_tags, confidence_score, review_flag, category_ids) → `d7e8f9a0b1c2` (multi-doc/export) → `e3f4a5b6c7d8` (is_approved, approved_markdown) → `a1b2c3d4e5f6` (proposal_json) → `c8b3f2a1d6e9` (remove APPROVED value, collapsing existing rows to DONE).

## 6. What's currently in flux (uncommitted, on top of `cffb589`)

The uncommitted changes to `database/crud.py`, `router/proposals.py`, `schemas/proposal.py`, `services/proposal_review_service.py` are a **second, independent round of changes**:
- Added: `GET /proposal/stats` + `ProposalStatsResponse` + `get_proposal_status_counts`/`get_proposal_stats` (dashboard breakdown by status).
- Added: `DELETE /proposal/{proposal_id}` soft-delete + `delete_proposal` crud/service functions.
- Removed: a commented-out `GET /proposal/{proposal_id}` route.
- **Removed: `POST /proposal_sections/{section_id}/regenerate` and `POST /proposal/sections/{section_id}/approve` router endpoints**, while leaving their backing service functions (`regenerate_section`, `approve_section`) intact and now unused.

**This last point is the key open question for anyone picking up this area next:** as the code stands, a reviewer can only edit section content and move the whole-proposal status forward manually — there is no reachable per-section approve or regenerate-with-quality-check action, despite that logic being otherwise complete and working. Confirm with whoever owns this area whether this is an in-progress retirement of the feature or an accidental omission before building anything on top of it.
