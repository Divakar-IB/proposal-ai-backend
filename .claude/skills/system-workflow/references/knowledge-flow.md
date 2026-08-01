# Knowledge Ingestion Flow

Scope: "knowledge documents" = organizational knowledge base content managed through `router/documents.py`, modeled by `KnowledgeDocument`/`KnowledgeChunk`. Distinct from `RequirementDocument` (the client/RFP upload, see [requirement-document-flow.md](requirement-document-flow.md)), which shares only the extraction/S3/arq infrastructure.

## 0. How processing actually gets triggered

`tasks/arq_pool.py:12-30` — `get_arq_pool()` unconditionally returns a `_NoOpArqPool`, whose `enqueue_job()` logs a warning and returns `None`. The real `arq.create_pool(...)` call is commented out. Nothing in the repo calls `get_arq_pool`/`enqueue_job` for this flow.

Instead, `router/documents.py` triggers processing via FastAPI's `BackgroundTasks.add_task`:
- `router/documents.py:138` — on file replace during update
- `router/documents.py:186` — on create

Separately, `tasks/arq_worker.py:27-28` defines `knowledge_document_job(ctx, document_id)` (registered in `WorkerSettings.functions`, `:44`) which calls the same `process_knowledge_document(document_id)` — an Arq worker process *could* run it, but nothing currently enqueues that job. So today, processing runs in-process, inline in the API server's background-task thread — not on a separate worker/queue.

## 1. Upload — entry point, S3 storage, DB row creation

**`POST /document/upload`** — `router/documents.py:64-189`. Multipart form: `document_name`, `description`, `category_id`, `availability_status` (default `ACTIVE`), `tags: list[str]`, optional `file`, optional `document_id` (create vs. update-in-place).

**Create path** (no `document_id`):
1. `:84-89` — validates `category_id` against an active `Category` row (404 if missing).
2. `:154` — derives `extension` from the filename suffix (lower-cased, dot stripped).
3. `:157-161` — builds the S3 key via `S3PathBuilder.knowledge_document(user_id, category_id, filename)` (`utilities/s3_service.py:32-54`):
   ```
   input/knowledge/{user_id}/{category_id}/{uuid4().hex}/{uuid4()}{extension}
   ```
   (no `document_id` exists yet, so the folder segment is a fresh random UUID hex).
4. `:163` — `s3_service.upload_file(file, s3_key)` (boto3 `upload_fileobj`, `utilities/s3_service.py:121-132`). The DB row is only created if this upload succeeds.
5. `:172-183` — creates `KnowledgeDocument(title, description, file_name, file_path=s3_key, extension, category_id, user_id, tags, availability_status)` via `create_knowledge_document` (`database/crud.py:116-120`). Model defaults: `status=IngestionStatus.PENDING`, `version=1`.
6. `:186` — schedules `process_knowledge_document(document.id)` as a background task.
7. Returns `DocumentResponse` including a 1-hour presigned S3 URL (`s3_service.generate_presigned_url`, `utilities/s3_service.py:267-280`).

**Update path** (`document_id` provided, `:91-141`):
- Always updates metadata (`title`, `description`, `category_id`, `availability_status`, `tags`).
- If a new file is supplied: builds a new S3 key (this time using the real DB id as folder segment), uploads it, deletes the **old** `file_path` from S3 (`:130`), bumps `version += 1`, updates `file_name`/`file_path`/`extension`/`version` via `update_knowledge_document` (`database/crud.py:123-128`).
- Only re-schedules `process_knowledge_document` if a new file was uploaded — metadata-only updates don't re-trigger processing.

**Table:** `knowledge_documents` (`database/models.py:65-91`). Columns: `title`, `description`, `file_name`, `file_path` (S3 key), `extension`, `category_id` (FK), `user_id` (FK), `version`, `tags` (`ARRAY(String)`), `status` (`IngestionStatus`), `availability_status` (`DocumentAvailability`), `extracted_markdown` (nullable, filled by extraction). Relationships: `category`, `uploader`, `chunks` (cascade `all, delete-orphan`).

**Other routes:**
- `GET /document/list` (`:192-205`) — paginated, filterable by `category_id`, `search` (title `ILIKE`), `status` (this actually filters `availability_status`, not `IngestionStatus` — see `build_knowledge_documents_query`, `database/crud.py:101-113`). Only `is_active=True`.
- `GET /document/{id}` (`:208-217`), `GET /document/{id}/download` (`:220-253`, streams S3 bytes as an attachment).
- `DELETE /document/{id}` (`:256-273`) — deletes the S3 object, then soft-deletes the row (`is_active=False`). **Does not** clean up the associated `KnowledgeChunk` rows or Pinecone vectors — that cleanup only happens on the re-processing path (`tasks/document_processing.py`), not on delete. This can leave orphaned vectors/chunks behind after a document delete.

## 2. Background processing orchestration

`process_knowledge_document(document_id)` — `tasks/document_processing.py:42-126`. Opens its own DB session via `db_session()` since the request-scoped session is already closed.

1. `:52-55` — reloads the document; aborts if not found.
2. `:57` — **status PENDING → PROCESSING**.
3. `:60-62` — downloads the S3 object to a local temp file (`s3_service.download_to_tempfile`).
4. `:72` — `extract_document` → `run_extraction(...)` (§3).
5. `:77` — persists `extracted_markdown`.
6. `:79-80` — `root_prefix = "{category.name} > {document.title}"`; `build_chunks(extracted, root_prefix)` (§4).
7. `:83` — `generate_embeddings(chunks)` (§5).
8. `:88-89` — wipes prior state before re-writing: `delete_document_vectors(document_id)` (Pinecone) + `delete_knowledge_chunks_for_document` (Postgres) — this is what makes re-processing on a new file version idempotent instead of leaving duplicates.
9. `:91-97` — `upsert_chunks(...)` writes to Pinecone (§6), returns vector IDs aligned with `chunks`.
10. `:100-112` — builds `KnowledgeChunk` rows zipped with `vector_ids`, bulk-inserts via `create_knowledge_chunks`.
11. `:115` — **status PROCESSING → INDEXED** (terminal success).
12. On any exception in the try block (`:118-120`): **status → FAILED**.
13. `finally` (`:122-125`): deletes the local temp file regardless of outcome.

## 3. Extraction stage

Shared entry point (also used by the requirement-document pipeline): `run_extraction(file_path, source_filename, extension)` — `extraction/factory.py:24-29`. Dispatch registry (`:7-14`): `pdf→PDFExtractor`, `docx→DocxExtractor`, `png/jpg/jpeg→ImageExtractor`, `md→MarkdownExtractor`. Raises `ValueError` for anything else (no `.txt`/`.pptx`/`.xlsx` support).

Shared output shape (`extraction/base.py:14-29`): `ExtractedPage(page_number, markdown, extraction_method)` + `ExtractedDocument(markdown, source_filename, pages)`; pages joined with `"\n\n"`.

- **PDFExtractor** (`extraction/pdf_extractor.py`) — PyMuPDF. Per page decides scanned-vs-native: native text < 40 chars (`MIN_NATIVE_TEXT_CHARS`) → scanned; or image coverage ≥60% of page area even with some text → scanned. Native path walks text blocks/lines/spans, computing a bold-ratio + max font size per line, scored against an estimated document body font size via the shared heading detector to optionally prefix `#`/`##`/`###`. Scanned path rasterizes at 200 DPI and runs OCR.
- **DocxExtractor** (`extraction/docx_extractor.py`) — python-docx, walks raw XML body children (so paragraphs/tables interleave in true document order). Named Word heading styles map directly to Markdown (`Heading 1→#`, etc.); unstyled paragraphs fall back to the same formatting-based heading detector. Tables render as GitHub-flavored Markdown. Whole DOCX becomes one page (no reliable page boundaries). Note: line 35 has a leftover `print(markdown)` debug statement that fires on every DOCX extraction.
- **MarkdownExtractor** — `.md` files are read as-is, single page, no re-detection (headings assumed already present).
- **ImageExtractor** — standalone image uploads go straight to OCR, single page.
- **OCR engine** (`extraction/ocr_engine.py`) — `StructuredOCREngine`, a lazy singleton over PaddleOCR's `PPStructureV3`. Pre-warmed at Arq worker boot (`tasks/arq_worker.py:16-24`) specifically to avoid a multi-GB first-run model download inside a job — but since this flow currently runs via FastAPI `BackgroundTasks` in the API process (§0), that pre-warm doesn't apply unless the API process separately triggers it. `extraction/ocr_extractor.py` is an unrelated, unused standalone dev script (hardcoded path, runs at import time) — not part of the live pipeline.
- **Heading detector** (`extraction/heading_detector.py`) — shared scoring function combining numbering-pattern regex, font-size delta vs. body size, bold/underline ratio, word count, and trailing punctuation into a heading score; threshold `3.0`; heading depth from either numbering depth or size-delta bands.

## 4. Chunking stage

`chunk_document(document, root_prefix, chunk_size=500, chunk_overlap=50)` — `chunking/pipeline.py:14-44`.

1. Precomputes page offsets matching how pages were joined, to approximate a source page per chunk later.
2. `split_by_headers(document.markdown)` (`chunking/markdown_splitter.py`) — LangChain `MarkdownHeaderTextSplitter` on `#`/`##`/`###`, `strip_headers=True`. Returns `(content, breadcrumb)` pairs.
3. Per section: `full_breadcrumb = "{root_prefix} > {heading_breadcrumb}"`; approximates the source page by locating the first 200 chars of the section in the full markdown; `split_oversized_section` sub-splits anything over 500 tiktoken (`cl100k_base`) tokens via `RecursiveCharacterTextSplitter.from_tiktoken_encoder(chunk_size=500, chunk_overlap=50)`. Each resulting piece is stored **breadcrumb-prefixed**: `f"{full_breadcrumb}: {piece}"` — this prefixed text is what actually gets embedded and stored, not the raw section text. `chunk_index` is a running counter across the whole document.

Defaults chosen (per inline comment) as "small enough for focused retrieval matches, large enough to keep coherent context."

## 5. Embedding stage

`embed_texts(texts)` — `embedding/embedder.py:6-14`, batches of 32 (`BATCH_SIZE`). Each batch → `HFInferenceEmbeddingClient.embed(batch)` (`embedding/hf_inference_client.py:9-20`): a `requests.post` to the Hugging Face Inference feature-extraction endpoint with `Authorization: Bearer {api_token}`. No explicit dimension validation in code — the Pinecone index is configured for 1024 dims (`config.py:39`, commented "BGE-M3 embedding size"), implying the configured model is expected to be BGE-M3-compatible, but this isn't enforced.

`embed_query(text)` (`embedding/embedder.py:17-19`) is the retrieval-time counterpart — same endpoint, single string, used at generation time (see proposal-generation-flow.md).

## 6. Vector store stage (Pinecone)

**Client** (`vectorstore/pinecone_client.py`) — `PineconeService` lazily creates a `Pinecone` client and returns `client.Index(config.pinecone.index_name)`.

**Index creation** (`vectorstore/index_manager.py::create_index`) — checks for the configured index name, creates a `ServerlessSpec` index if absent. Not invoked from the ingestion pipeline itself — an out-of-band/manual bootstrap step.

**Upsert** — `upsert_chunks(document_id, category_id, source_filename, chunks, embeddings)` (`vectorstore/knowledge_store.py:14-46`), called from `tasks/document_processing.py:91-97`:
- Vector id: `f"kdoc-{document_id}-{chunk_index}-{uuid4().hex[:8]}"` — **not deterministic** across re-processing runs (consistent with the delete-then-recreate approach rather than upsert-by-stable-id).
- Metadata per vector: `document_id`, `category_id`, `breadcrumb`, `page_number` (0 if unknown), `chunk_index`, `source_filename`, `text` (the breadcrumb-prefixed chunk content).
- **No Pinecone namespace is used anywhere** in this codebase — everything lives in the default namespace of one index. Category isolation is done entirely via the `category_id` metadata filter at query time.

**Delete** — `delete_document_vectors(document_id)` — `index.delete(filter={"document_id": document_id})`, swallowing `NotFoundError` (e.g. first-ever processing run).

**Query** — `query_chunks(query_embedding, top_k=5, category_ids=None)` (`vectorstore/knowledge_store.py:60-88`) — optional `{"category_id": {"$in": category_ids}}` filter, `include_metadata=True`. Maps matches to `{text, breadcrumb, document_id, page_number, source_filename, score}`. This is the function proposal generation calls at retrieval time.

**Postgres mirror:** `knowledge_chunks` table (`database/models.py:94-109`) is documented in-code as "Postgres source of truth for chunks embedded into Pinecone." Columns: `knowledge_document_id` (FK), `chunk_index`, `breadcrumb`, `content` (same prefixed text as Pinecone's `text` metadata), `page_number`, `token_count`, `pinecone_vector_id` (unique). Rows are wiped and recreated on every re-processing run.

## 7. Retrieval during proposal generation

See [proposal-generation-flow.md](proposal-generation-flow.md) §3 for the full retrieval mechanics. Summary: retrieval is per-section, per-generation-request, gated by `GenerationMode.KNOWLEDGE_AUGMENTED` + a cheap "any chunks exist at all" check, filtered only by the proposal's `category_ids` (in practice always unfiltered — see the top-level SKILL.md gap list), `top_k=8`, using the same HF embedding endpoint as ingestion. `DocumentAvailability` (`ACTIVE`/`INACTIVE`) is **not** part of the Pinecone metadata and is **not** checked at query time — an `INACTIVE` document's chunks remain retrievable.

## 8. Status/enum summary

- **`IngestionStatus`** (`database/db_enum.py:7-11`) — `PENDING` (default) → `PROCESSING` → `INDEXED` (success) or `FAILED` (any exception). No automatic path back to `PENDING`; only a fresh file upload re-triggers processing (which itself re-sets `PROCESSING`, not `PENDING` first).
- **`DocumentAvailability`** — `ACTIVE`/`INACTIVE`, user-controlled visibility flag; does not gate retrieval (see above).
- Soft-delete via `is_active` (from `BasicModel`) — rows are never hard-deleted by this pipeline.

## 9. Arq mechanics (as coded, currently inert for this flow)

`tasks/arq_worker.py` registers `knowledge_document_job`, `requirement_document_job`, `proposal_generation_job` (`job_timeout=900`s), with a startup hook that pre-warms the OCR engine. Intended usage per `tasks/arq_pool.py`'s comments: `pool = await get_arq_pool(); await pool.enqueue_job("knowledge_document_job", document_id)`. Actual state: `get_arq_pool()` always returns the no-op pool; no call site anywhere in the repo actually calls `enqueue_job`. Whether an Arq worker process is even run in the current deployment, and if so what would enqueue work to it, is not resolvable from the code alone.

## File-level source map

| Concern | File |
|---|---|
| Upload/list/get/download/delete routes | `router/documents.py` |
| Schemas / enums | `schemas/document.py`, `database/db_enum.py` |
| ORM models | `database/models.py` |
| CRUD | `database/crud.py` |
| Orchestration | `tasks/document_processing.py` |
| Arq worker / pool | `tasks/arq_worker.py`, `tasks/arq_pool.py` |
| Extraction | `extraction/factory.py`, `extraction/base.py`, `extraction/pdf_extractor.py`, `extraction/docx_extractor.py`, `extraction/markdown_extractor.py`, `extraction/image_extractor.py`, `extraction/ocr_engine.py`, `extraction/heading_detector.py` |
| Chunking | `chunking/pipeline.py`, `chunking/markdown_splitter.py`, `chunking/recursive_splitter.py`, `chunking/tokenization.py`, `chunking/models.py` |
| Embedding | `embedding/embedder.py`, `embedding/hf_inference_client.py` |
| Vector store | `vectorstore/knowledge_store.py`, `vectorstore/pinecone_client.py`, `vectorstore/index_manager.py` |
| S3 | `utilities/s3_service.py` |
| Config | `config.py` |
