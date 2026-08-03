# Requirement Document Flow

Scope: the client/RFP document pipeline — distinct from `knowledge_documents` (see [knowledge-flow.md](knowledge-flow.md)), touched only where the two intersect at retrieval time (§2g, §5).

## 1. Entry point — upload/create

**`POST /proposal/requirement-documents`** — `router/proposals.py:141-202`, mounted under prefix `/proposal`.

- Auth: `Depends(get_current_user)`.
- Request: multipart form — `file`, `proposal_name`, `client_name`, `additional_context` (optional).
- Response: `RequirementDocumentResponse` (`schemas/requirement_document.py:22-38`), HTTP 201.

Flow (`:161-202`):
1. `extension` derived from filename.
2. `S3PathBuilder.requirement_document(user_id, filename)` (§3) → `s3_service.upload_file`. 502 on failure.
3. Creates the `Proposal` row up front: `title=proposal_name`, `client_name`, `additional_context`, `status=ProposalStatus.INPROGRESS` (via `create_proposal`, `database/crud.py:193-197`). **This is the same `Proposal` row that generation later drafts into** — proposal identity begins at requirement-doc upload, not at a separate "create proposal" step.
4. Creates the `RequirementDocument` row: `file_name`, `file_path=s3_key`, `extension`, `user_id`, `proposal_id` (via `create_requirement_document`, `database/crud.py:161-165`). Default `status=DocumentStatus.UPLOADING`.
5. **Synchronously awaits** `process_requirement_document_pipeline(db, document, additional_context)` — no background queue (see §6). The HTTP response does not return until extraction + all three LLM calls + knowledge-matching complete.
6. If the pipeline leaves `status == FAILED`, raises HTTP 422. Otherwise returns document + parent-proposal fields flattened together.

The same router also exposes a **read-only** `GET /proposal/{proposal_id}/state` endpoint that surfaces the same data (via `get_requirement_documents_by_proposal_id`) plus every parsed document's `summary`/`knowledge_matches`/`capability_tags`, aggregated by `services/proposal_wizard_service.py` into a `SummaryStep` in a multi-step wizard response. It does not create requirement documents itself. (This endpoint previously lived in a separate unprefixed `router/proposal_temp.py`, now removed.)

No other router exposes requirement-document endpoints.

## 2. Extraction / parsing pipeline

Orchestrator: `process_requirement_document_pipeline(db, document, additional_context)` — `tasks/requirement_processing.py:31-92`.

**a. Status → EXTRACTING** (`:48`) — one status covers extraction, parsing, classification, summarization, and knowledge-matching; there's no separate "PARSING" state.

**b. Fetch from S3** (`:52`) — downloads to a local tempfile. Deliberately re-downloads from S3 rather than reusing the original upload buffer.

**c. Text extraction** (`:55`) — `run_extraction(...)` (`extraction/factory.py:24-29`), the **same** dispatch used by the knowledge-document pipeline. No requirement-specific extractor logic.

**d. Structured requirement extraction (LLM, fatal on failure)** — `parse_requirements(extracted.markdown, additional_context)` (`:61`, `requirements_parsing/parser.py:17-76`):
- System prompt (`prompts/requirement_extraction.py:7-15`): "extract a structured summary by calling the `extract_requirements` tool... never invent values... array fields must be `[]` not `null`."
- User content: extracted markdown, `additional_context` appended if present.
- Forces a tool call (`EXTRACT_TOOL`, name `extract_requirements`, parameters generated directly from `RequirementsSchema.model_json_schema()`).
- **Repair loop**, up to 3 attempts: on provider-side schema rejection (`APIStatusError`), missing tool call, or JSON/Pydantic validation failure, appends a corrective message and retries. After 3 failures, raises `ValueError` — **this step is fatal**, unlike capability classification below.

`RequirementsSchema` (`requirements_parsing/schema.py:6-27`):
```
project_title: str            (required)
project_type: Optional[str]
scope: str                    (required)
deliverables: list[str]       (default [])
budget_range: Optional[str]
timeline: Optional[str]
technical_requirements: list[str]  (default [])
evaluation_criteria: list[str]     (default [])
constraints: list[str]            (default [])
```
Docstring frames this explicitly as "the query input for retrieval in the proposal generation flow."

**e. Capability classification (LLM, non-fatal)** — `_classify_capabilities_safely` (`:95-104`) wraps `classify_capabilities` (`requirements_parsing/capability_classifier.py:11-33`) in a try/except that degrades to `[]` on any exception, explicitly because this is "enrichment metadata, not a blocking step."
- Sends **no raw document text** — only `json.dumps(requirements_dict)` as the user message, paired with a system prompt (`prompts/capability_classification.py`) that injects the fixed `KNOWLEDGE_CATEGORIES` vocabulary from `constants.py`.
- Tool: `report_capability_tags`, schema `CapabilityClassification` (`requirements_parsing/capability_schema.py`: `tags: list[{name, confidence}]`).
- Single call, no repair loop; missing tool call → `ValueError`, caught by the safe wrapper.

**f. Summary generation (LLM)** — `summarize_requirements(requirements_dict, additional_context)` (`:67`, `requirements_parsing/summary.py:15-31`). Again uses the **structured JSON**, not raw text, as input. Plain completion (no tool calling), instructed to produce a 2-4 sentence Markdown summary "for a proposal writer's sidebar view."

**g. Knowledge-match scoring** — `_compute_knowledge_matches(db, summary)` (`:107-141`):
- Short-circuits to `[]` if no knowledge chunks exist anywhere, or the summary is blank.
- Otherwise: `embed_query(summary)` → `query_chunks(embedding, top_k=30)` against the **entire** Pinecone index (no category filter here).
- Dedupes to the single best-scoring chunk per `document_id`, fetches those documents' titles, builds `{document_id, title, source_filename, breadcrumb, match_percent}`, sorted descending, truncated to top 10. This is the `knowledge_matches` field surfaced to the UI.

**h. Final persist / status → PARSED** (`:73-81`) — writes `extracted_markdown`, `parsed_data`, `capability_tags`, `summary`, `knowledge_matches`, `status=PARSED` all in one `update_requirement_document` call.

**i. Failure path** — any exception → **status → FAILED**; `finally` always deletes the downloaded tempfile.

**LLM client:** all three calls go through `GroqChatClient` (`llm/chat_client.py`), a thin wrapper over the OpenAI SDK pointed at Groq (`openai/gpt-oss-120b`). `.complete()` supports forced tool calls (`temperature=0.2` default); `.stream_complete()` (used only in proposal generation, not here) yields plain text deltas.

## 3. Storage

**Table `requirement_documents`** (`database/models.py:112-132`, extends `BasicModel`: `id`, `is_active`, `created_at`, `updated_at`):
- `file_name`, `file_path` (S3 key, not a public URL), `extension`
- `user_id` (FK), `proposal_id` (FK, nullable, indexed)
- `status` (`DocumentStatus`, default `UPLOADING`)
- `extracted_markdown` (nullable Text)
- `parsed_data` (nullable JSONB — the `RequirementsSchema` dump)
- `capability_tags` (nullable JSONB — list of `{name, confidence}`)
- `summary` (nullable Text)
- `knowledge_matches` (nullable JSONB — list of `{document_id, title, source_filename, breadcrumb, match_percent}`)

Relationships: `uploader` → `User.requirement_documents`; `proposal` → `Proposal.requirement_documents` (`lazy="selectin"`, ordered by `created_at`) — loading a `Proposal` eagerly loads all its requirement documents.

**CRUD** (`database/crud.py:149-189`): `get_requirement_document_by_id` (filters `is_active`), `create_requirement_document`, `get_requirement_documents_by_proposal_id` (filters active, ordered by `created_at` — used by both the wizard endpoint and generation), `update_requirement_document` (generic setattr + commit).

**S3 key:** `S3PathBuilder.requirement_document(user_id, filename, requirement_document_id=None)` (`utilities/s3_service.py:57-76`):
```
input/requirements/{user_id}/{doc_segment}/{uuid4()}{extension}
```
Since the S3 key must be built before the row exists, `doc_segment` should ideally be the real row id — but the upload handler (`router/proposals.py:165`) doesn't pass `requirement_document_id`, so `doc_segment` is always a fresh UUID. The S3 folder segment and the Postgres row id are not correlated in practice.

There is no presigned-URL/download endpoint for the original requirement document (unlike knowledge documents, which have one).

## 4. Status/enum tracking

`DocumentStatus` (`database/db_enum.py:13-17`): `UPLOADING` (row default) → `EXTRACTING` (set at pipeline start) → `PARSED` (terminal success) or `FAILED` (terminal failure, → HTTP 422 from the upload endpoint). No retry/resume path back from `FAILED` — a failed document stays failed unless re-uploaded.

This is a separate enum namespace from `IngestionStatus` (knowledge documents) and `ProposalStatus` (the parent proposal).

## 5. Downstream use — feeding proposal generation

`generation/requirement_context.py` — two pure functions over `list[RequirementDocument]`:
- `build_combined_summary(...)` — concatenates each document's `.summary` under a `### {file_name} (#{id})` heading. **Defined but not called anywhere else** in generation — summaries are surfaced only via `GET /proposal/{proposal_id}/state` for the UI (using the near-duplicate `services/proposal_wizard_service.py::combined_summary`, which omits the heading for a single file), not fed to the LLM drafting step.
- `build_combined_requirements_json(...)` — builds `{file_name: document.parsed_data, ...}` and `json.dumps(..., indent=2)`. **This is the actual shape passed forward**: one filename-keyed JSON blob, each value the raw `RequirementsSchema` dict.

Consumed in `generate_proposal_stream` (`generation/proposal_generator.py`, see [proposal-generation-flow.md](proposal-generation-flow.md)):
- The full combined JSON string is embedded verbatim into every section's drafting prompt (grounding text, under a "Client requirements (structured)" heading).
- Per section, only that section's relevant `query_fields` (a fixed list of `RequirementsSchema` field names defined per section in `generation/sections.py`) are pulled out across all documents and joined with the section title to build the retrieval query text sent to Pinecone.

So requirement-document data enters generation exactly once, as the combined `parsed_data` blob — used both as literal LLM grounding and as the source of per-section retrieval queries. `summary`/`knowledge_matches`/`capability_tags` are UI/sidebar metadata only, never re-consumed by generation.

## 6. Async task queue mechanics

No active queue usage. The upload endpoint calls `process_requirement_document_pipeline` directly and synchronously — the docstring at `router/proposals.py:154-160` confirms this is intentional ("the caller gets the summary and matches back here directly instead of polling a separate status endpoint").

A standalone function `process_requirement_document(document_id)` (`tasks/requirement_processing.py:144-157`) exists as a documented "background entry point (e.g. an Arq job)... **Not currently used** by the upload endpoint." No Arq worker registration or enqueue call was found referencing it.

## Pipeline diagram (file:line index)

1. Upload: `router/proposals.py:146-202` → S3 (`utilities/s3_service.py:121-132`) + `create_proposal`/`create_requirement_document` (`database/crud.py:193-197,161-165`)
2. Orchestration: `tasks/requirement_processing.py:31-92`
   - status=EXTRACTING (`:48`) → S3 download (`:52`) → extraction (`:55`) → requirement parse LLM (`:61`) → capability classification LLM, non-fatal (`:65,95-104`) → summary LLM (`:67`) → knowledge-match scoring (`:70,107-141`) → persist + status=PARSED (`:73-81`) / status=FAILED (`:85-87`)
3. Storage: `database/models.py:112-132`, S3 key `utilities/s3_service.py:57-76`
4. Status enum: `database/db_enum.py:13-17`
5. Generation consumption: `generation/requirement_context.py:19-29` → `generation/proposal_generator.py:81-83,117-122` → `generation/nodes.py:20-58,61-107` → `prompts/proposal_generation.py:28-41`
6. No live async queue; synchronous await only.
