# Proposal Generation Flow

## 0. Orientation caveat

There are two parallel section-drafting code paths sharing the same low-level helpers (`generation/nodes.py`), plus some dead code. Know these before touching generation:

- **Path A — the live `/proposal/generate` pipeline**: a flat, sequential per-section loop in `generation/proposal_generator.py::generate_proposal_stream`. This is **not** a graph at runtime — `generation/state.py`'s `ProposalGenerationState`/`SectionState` TypedDicts (with `retry_count`/`feedback`/`confidence_score` fields) describe what looks like a draft→review→retry graph, but `generate_proposal_stream` never calls `run_quality_check` or `decide_section_status`. Every section is drafted once and immediately persisted as `APPROVED`. No graph library (no `langgraph`) is used anywhere in the repo.
- **Path B — manual single-section regenerate**: `services/proposal_review_service.py::regenerate_section` *does* use the full draft → quality-check → decide-status sequence, single-shot (`force_approve=False` always). As of the current working tree this function has **no router endpoint** — see [review-workflow.md](review-workflow.md) §6.
- **`generation/prompts.py`** (whole-document-in-one-call prompt) is unused dead code — nothing imports it. The prompt actually used for drafting is `prompts/proposal_generation.py`.
- **Arq/Redis is disabled** — `tasks/arq_pool.py` always returns a no-op pool. `tasks/arq_worker.py` registers `proposal_generation_job` (→ `tasks/proposal_generation.py::generate_proposal`), but nothing enqueues it. Generation runs synchronously inside the HTTP request/response cycle over SSE.
- **One proposals router**: `router/proposals.py` (prefix `/proposal`, tagged "Proposals"). The former second router `router/proposal_temp.py` (unprefixed, demo-only wizard support) has been folded into it — its endpoints are now `GET /proposal/{proposal_id}/state` and `GET`/`PATCH /proposal/{proposal_id}/sections`, with `proposal_id` as a path param. Its multi-file aggregation helpers live in `services/proposal_wizard_service.py`.

## 1. Entry point

**`POST /proposal/generate`** — `router/proposals.py:209-235`.

Request body — `ProposalGenerateRequest` (`schemas/proposal.py:15-18`):
```python
class ProposalGenerateRequest(BaseModel):
    proposal_id: int
    page_count: int
    generation_mode: GenerationMode   # "llm_only" | "knowledge_augmented"
```
No field for selecting specific requirement documents or section titles — the endpoint loads **all** requirement documents already attached to `proposal_id`, and section titles/order come from a hardcoded `SECTION_DEFINITIONS` list, not client input. Client name / additional context / proposal title were already captured earlier at requirement-document upload time (see [requirement-document-flow.md](requirement-document-flow.md)).

The endpoint itself just 404s if the proposal doesn't exist, then returns a `StreamingResponse` wrapping `generate_proposal_stream(proposal_id, page_count, generation_mode)`, `media_type="text/event-stream"`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

## 2. Control flow — `generate_proposal_stream` (`generation/proposal_generator.py`)

A LangGraph state machine (`generation/graph.py`), **not** a `for` loop:

```
START → load_context → draft_sections → compile_proposal → END
```

`generate_proposal_stream` only drives the graph via `astream(..., stream_mode="custom")` and translates writer events into SSE lines.

`draft_sections` owns the per-section fan-out **internally**: it resolves `get_stream_writer()` once, creates one asyncio task per section, and gathers them under an `asyncio.Semaphore(config.generation.resolved_concurrency)`. Each task runs `generation/section_runner.py::run_section` — one section's whole retrieve → draft → persist chain, so a section is still persisted the moment it individually finishes.

**Why not LangGraph's `Send` fan-out:** it has no native concurrency cap, so bounding it means fanning out in fixed batches with a superstep barrier between them — reintroducing the barrier wait concurrency is meant to remove — plus state reducers to accumulate `persisted_sections` and graph-level retry policy for per-section 429 backoff. A single node holding a semaphore expresses the same thing directly. This replaced a `start_section → retrieve → draft → persist_section` **cycle** that could only ever run one section at a time.

Concurrency defaults to **1**, which reproduces the original strictly-sequential behaviour exactly. Above 1 sections complete out of order; `assemble_markdown` sorts by `order_index`, so document order is unaffected.

1. **Load state** (`load_context`, inside `db_session()`):
   - Fetch `Proposal` (404-equivalent `ValueError` if missing).
   - Fetch all `RequirementDocument`s for this proposal.
   - `build_combined_requirements_json(...)` (see requirement-document-flow.md §5).
   - `has_knowledge = generation_mode == KNOWLEDGE_AUGMENTED and await has_any_knowledge_chunks(db)` — cheap existence check so an empty Pinecone index is never queried.
   - Capture `proposal_title`, `client_name`, `additional_context`, `user_id`, `category_ids`.
   - `delete_proposal_sections_for_proposal(...)` — wipes any prior sections so regeneration doesn't leave stale/duplicate rows.
   - `update_proposal(..., status=GENERATING, generation_mode, page_count)` — **status transition #1: INPROGRESS → GENERATING**.

2. **Per-section word target** (`:101`): `word_target = max((page_count * 500) // len(SECTION_DEFINITIONS), 100)`. `SECTION_DEFINITIONS` has 12 entries, so a 10-page proposal → ~416 words/section.

3. **Per section** — `section_runner.py::run_section`, under the semaphore:
   a. Emit SSE `section_start`.
   b. `section_state` built by `graph.py::_build_section_state`: `key`, `title`, `query_fields`, `drafting_note` (word target + outline instruction), `retrieved_chunks: []`.
   c. **Retrieval**: `retrieve_chunks_for_section(...)` (§3), own `db_session()`. Logs the chunk count; 0 chunks is not an error — `build_context_block` emits an explicit `(no relevant context retrieved)` placeholder and `DRAFT_SYSTEM_PROMPT` has a branch for writing from general practice.
   d. **Token sizing** (`generation/token_budget.py`) — done after retrieval, since the retrieved context is the largest and most variable part of the prompt. `completion_tokens_for(word_target)` then `clamp_completion_tokens(...)` to keep prompt + completion under `groq.tokens_per_minute × request_budget_ratio`. A clamp logs a warning (the section will run short); a prompt that alone exceeds the ceiling logs an error naming `TOP_K_SECTION_CHUNKS`.
   e. **TPM pre-flight**: `rate_limit.governor.acquire(...)` waits if the last response's `x-ratelimit-remaining-tokens` is too thin for a request this size.
   f. **Draft (streamed)**: `draft_one_section_stream(...)` under `run_with_rate_limit_retry` — each delta re-emitted as SSE `section_chunk` **with the section `name`** so concurrent chunks are attributable. A 429 waits exactly `Retry-After` and retries only this section; a 413 raises `RequestTooLargeError` immediately (waiting cannot fix a too-large request).
   g. **Validation** — `validate_section_outcome(...)` **before** persisting: empty content → `EmptySectionError`, `finish_reason != "stop"` → `TruncatedSectionError`. See §2a.
   h. `citations = section_citations(section_state)` — just `{breadcrumb, source_filename}` per retrieved chunk, not derived from LLM output.
   i. **Persist immediately** (own `db_session()` block): insert `ProposalSection(section_key, title, order_index, content, citations, status=APPROVED)` — **every section is force-approved, no quality gate, in this path.**
   j. Emit SSE `section_done`.
   - On any exception: `draft_sections` gathers with `return_exceptions=True` so no task is orphaned mid-flight, then raises. **status → FAILED** with `error_message` naming the section, yield SSE `error`, stream ends (no `done` event). **Sections that already persisted stay persisted.**

### 2a. The reasoning-token trap — read before touching the drafting call

`openai/gpt-oss-120b` is a reasoning model. It emits reasoning on a **separate `delta.reasoning` field** (`ChoiceDelta.model_config["extra"] == "allow"`) that is billed against the same `max_completion_tokens` allowance as the visible draft but is never streamed to the client.

`stream_complete` reads only `delta.content`, so before this was fixed a response that reasoned until it ran out of room yielded an empty string and was **persisted as a finished-but-empty section** — no error, no log. Measured on one section at a 300-token cap: model default → **301 reasoning tokens, 0 content tokens, empty section**; `reasoning_effort="low"` → 25 reasoning tokens, 204 words written, same billed cost.

Three consequences:
- `config.generation.reasoning_effort` defaults to `"low"` and is a **correctness** setting. Raising it without raising the per-section cap re-creates empty sections.
- **Never set `max_completion_tokens` without it** — a tighter cap makes the failure more likely, not less.
- `StreamOutcome` (`llm/chat_client.py`) exists so the caller can tell a finished section from a truncated or empty one; the yielded text alone cannot. Anything that persists a streamed section must check it.

4. **After all sections succeed** (`:159-170`):
   - `assemble_markdown(proposal_title, persisted_sections)` (`generation/markdown_sections.py`) → `# {title}\n\n` + `## {section title}\n\n{content}` per section.
   - Upload to S3: `output/proposals/{user_id}/{proposal_id}/proposal.md`.
   - `update_proposal(..., markdown_path=s3_key, status=REVIEW)` — **status transition #2: GENERATING → REVIEW**.
   - Yield SSE `done`.

### Section definitions (`generation/sections.py`, 12 fixed sections, fixed order)
`executive_summary`, `company_profile`, `understanding_of_requirements`, `proposed_solution`, `technology_stack`, `proposed_team_structure`, `project_implementation_plan`, `non_functional_requirements_compliance`, `security_and_data_privacy_framework`, `commercial_proposal`, `competitive_differentiators`, `declaration_and_authorised_undertaking`. Each carries a `query_fields` string (which `RequirementsSchema` fields drive its retrieval query) and, for several sections, an `outline` (subsection headings the drafter must use in order).

## 3. Retrieval — how knowledge + requirement context feed generation

**Requirement context:** see requirement-document-flow.md §5 — the combined `parsed_data` JSON is embedded verbatim into every section's draft prompt, regardless of retrieval.

**Knowledge-base retrieval** (`retrieve_chunks_for_section`, `generation/nodes.py:39-58`) — per section, not once per proposal:
1. Returns `[]` immediately if `has_knowledge` is `False`.
2. `_build_query_text` (`:20-36`): for the section's `query_fields`, pulls that field's value out of *every* requirement document's parsed dict, joins `[section_title, *field_values]` with newlines.
3. `embed_query(query_text)` — same HF Inference endpoint used at ingestion.
4. `query_chunks(query_embedding, top_k=8, category_ids=category_ids)` (`vectorstore/knowledge_store.py`) — Pinecone query, `filter = {"category_id": {"$in": category_ids}} if category_ids else None`.
   - **Gap:** `Proposal.category_ids` is never assigned by any live code path (only ever read) — so in practice this filter is always absent and retrieval is effectively unfiltered by category today.
5. Result stored on `section_state["retrieved_chunks"]`, rendered into the draft prompt via `build_context_block` (`prompts/proposal_generation.py`): each chunk as `[{breadcrumb}]\n{text}`, or the literal `"(no relevant context retrieved)"` if empty. Also becomes the section's persisted `citations`.

## 4. LLM calls, prompts, structured output

Client: `llm/chat_client.py::GroqChatClient` (Groq-hosted `openai/gpt-oss-120b`, OpenAI-compatible API). `.complete()` (non-streaming, supports forced tool calls, `temperature=0.2` default) vs. `.stream_complete()` (plain streaming, no tool-calling — "streaming + forced tool calls don't mix cleanly").

**Call 1 — per-section draft** (`generation/nodes.py:61-107`, prompts in `prompts/proposal_generation.py`):
- System (`DRAFT_SYSTEM_PROMPT`): ground claims in retrieved context if present; otherwise write from generic best practice without fabricating specifics; only emit a `GAP:` line when the *client requirements* (not the knowledge base) are missing needed info; output section body only.
- User (`DRAFT_USER_TEMPLATE`): section title, drafting note (word target + outline), combined `requirements_json`, retrieved-context block, prior feedback (always `"(none — first draft)"` on the live `/generate` path, since no quality check ever runs there).
- Output: raw Markdown, streamed token-by-token into the SSE response.

**Call 2 — quality check** (`generation/nodes.py:110-139`, prompts in `prompts/proposal_review.py`) — **only invoked by `regenerate_section`, never by the main `/generate` stream**:
- Forces a tool call validated against `QualityCheckResult` (`generation/schema.py`): `{approved: bool, feedback: Optional[str], confidence_score: float}`.
- `decide_section_status(result, force_approve=False)` (`:142-158`): approved → `(APPROVED, None, review_flag=False)`; not approved + `force_approve` → `(APPROVED, feedback, review_flag=True)`; not approved, no force → `(NEEDS_REVISION, feedback, review_flag=True)`. `regenerate_section` always passes `force_approve=False`.

There is no LLM call that produces a single structured "whole proposal JSON" — `proposal_json` is derived after the fact by re-parsing assembled Markdown (see export-flow.md), not produced directly by an LLM call.

## 5. What gets stored where

**`proposals` table**, columns touched during/after generation:
- `status`, `generation_mode`, `page_count` — set at generation start.
- `markdown_path` — S3 key of assembled Markdown, set on success.
- `error_message` — set only on failure.
- `proposal_json`, `approved_markdown`, `is_approved`, `docx_path`, `pdf_path` — **never written by any live code path.** `proposal_json` is exposed read-only in responses but nothing calls `update_proposal(..., proposal_json=...)`; export computes an equivalent shape live on every export call instead (see export-flow.md). These columns exist for a planned "freeze on approval" feature that isn't wired up.

**`proposal_sections` table**: one row per section — `proposal_id`, `section_key`, `title`, `order_index`, `content`, `citations` (JSONB), `status` (always `APPROVED` from the main stream), `retry_count` (default 0, only incremented by `regenerate_section`), `confidence_score`/`review_flag` (only set by `regenerate_section`, which currently has no router endpoint).

**S3**: assembled Markdown at `output/proposals/{user_id}/{proposal_id}/proposal.md`. No DOCX/PDF artifact is ever persisted to S3 by generation (export streams bytes directly instead — see export-flow.md).

## 6. `ProposalStatus` transitions during generation

`INPROGRESS` (set at requirement-doc upload) → `GENERATING` (generation start) → `REVIEW` (all sections done) or `FAILED` (exception mid-loop). Full enum history and the rest of the lifecycle (manual override, `DONE`) are covered in [review-workflow.md](review-workflow.md).

## 7. Async task mechanics

`/proposal/generate` does not enqueue a background job — it calls `generate_proposal_stream` in-process and streams SSE directly from the request handler; generation runs for the lifetime of the HTTP connection. The parallel Arq path (`proposal_generation_job` → `tasks/proposal_generation.py::generate_proposal`, which fully drains the stream with `async for _ in ...: pass`) is registered but unreachable — nothing calls `enqueue_job` (see SKILL.md's dead-code list).

## 8. Multi-document proposal support

Migration `d7e8f9a0b1c2_multi_document_proposals_and_export.py` inverted the original one-proposal-to-one-document relationship: dropped `proposals.requirement_document_id`, added `requirement_documents.proposal_id` (nullable FK, indexed) instead, backfilling existing rows. Post-migration: `Proposal.requirement_documents` is one-to-many (`lazy="selectin"`, ordered by `created_at`).

At generation time, all documents on the proposal are pulled via `get_requirement_documents_by_proposal_id` and merged: `build_combined_requirements_json` keys the combined dict by `file_name`, one entry per document. Per-section retrieval iterates every document's value for the relevant `query_fields`, folding all documents' fields into one retrieval query per section rather than querying per document.

Note: the current upload endpoint (`POST /proposal/requirement-documents`) always creates a **new** `Proposal` row per call — there's no exposed "attach another document to an existing proposal_id" mode in the router, even though the model/schema fully support multiple documents per proposal.

## Other migrations of note

- `b71d4e2a9f6c` — adds the `generationmode` Postgres enum, `proposals.generation_mode`, `proposals.page_count`, `proposal_sections.title`.
- `a1b2c3d4e5f6` — adds `proposals.proposal_json` (JSONB, nullable) — per §5, effectively unused today.
