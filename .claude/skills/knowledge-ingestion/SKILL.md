---
name: knowledge-ingestion
description: Use when creating or modifying the knowledge-base document ingestion pipeline — upload routes, text extraction, chunking, embedding, or Pinecone vector storage.
---

# Knowledge Ingestion Skill

## Purpose

This skill governs the pipeline that turns an uploaded organizational knowledge document into retrievable vector chunks: upload → extract → chunk → embed → store in Pinecone (mirrored in Postgres). It shares extraction infrastructure with the requirement-document pipeline — see the `system-workflow` skill's `knowledge-flow.md` reference for the full current-state narrative (file:line detail, what's live vs. dead). This file is the rulebook for extending it correctly.

Tech stack

- PyMuPDF / python-docx / PaddleOCR (`PPStructureV3`) for extraction
- LangChain `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` for chunking
- Hugging Face Inference API for embeddings
- Pinecone (single index, default namespace only)

---

# Extraction

- `extraction/factory.py::run_extraction` is the **single shared entry point** for both the knowledge and requirement-document pipelines. Any change here affects both flows — check both before modifying.
- Adding a new file type: register it in the `_EXTRACTORS` dispatch map, implement `BaseExtractor.extract(file_path, source_filename) -> ExtractedDocument`, and pick the correct `ExtractionMethod` enum value (add one if genuinely new). Don't special-case a new extension outside the registry.
- Reuse the shared heading detector (`extraction/heading_detector.py::classify_heading`) for any new text-based extractor rather than inventing a new heading-scoring heuristic — it already balances numbering patterns, font-size delta, bold/underline ratio, and word count.
- Never leave debug output (`print(...)`) in an extractor on the live path — it runs on every document of that type.
- Don't add a standalone dev/test script that imports production extraction internals unless it's clearly out-of-band (existing precedent: `extraction/ocr_extractor.py` is intentionally a scratch script, not wired into `factory.py`).

---

# Chunking

- Keep `chunk_size`/`chunk_overlap` (default 500/50 tokens, `cl100k_base`) tuned for retrieval quality, not extraction convenience — smaller chunks improve retrieval precision, larger chunks preserve context for drafting. Changing the default affects every future re-embedding, not existing vectors.
- Always store the **breadcrumb-prefixed** content (`"{root_prefix} > {heading path}: {chunk text}"`) as both the embedded text and the persisted `KnowledgeChunk.content` — retrieval-time citations depend on the breadcrumb being present in the stored text, not derived separately.
- `chunk_index` must remain a running counter across the whole document (not reset per section) — it's part of the vector id and part of ordering.

---

# Embedding

- All embedding calls (ingestion and query-time) must go through the same client/model (`embedding/embedder.py` / `embedding/hf_inference_client.py`) — embedding space must stay consistent between what's indexed and what's queried.
- The Pinecone index's `dimension` (`config.pinecone.dimension`) is fixed at index-creation time. **Changing the embedding model to one with a different output dimension requires recreating the Pinecone index** (`vectorstore/index_manager.py::create_index`) and re-processing every existing knowledge document — it cannot be changed in place.

---

# Vector Storage (Pinecone)

- This codebase uses **no Pinecone namespaces** — everything lives in one index's default namespace, with tenant/category isolation done entirely via metadata filters (`category_id`) at query time. If you add a new dimension of isolation (e.g. per-organization), decide deliberately whether to use metadata filtering (consistent with current pattern) or namespaces (a bigger structural change) — don't mix both without a clear reason.
- Any new metadata field you add to a vector at upsert time is **not automatically filterable** — it must also be added to the query-side filter construction (`vectorstore/knowledge_store.py::query_chunks`) if it's meant to gate retrieval. Concretely: `DocumentAvailability` (`ACTIVE`/`INACTIVE`) is currently *not* written into vector metadata and *not* checked at query time, so inactive documents remain retrievable — if you fix this, you must both add it to `upsert_chunks`'s metadata payload and add it to the query filter, and re-process existing documents (metadata on already-indexed vectors won't retroactively update).
- Vector ids in this pipeline are **not stable/deterministic** across re-processing (they include a random suffix) — this is intentional, because idempotency is achieved by delete-then-recreate, not upsert-by-fixed-id. Don't change to a deterministic id scheme without also changing the delete-before-upsert logic to match, or you'll accumulate orphaned vectors.

---

# Idempotency & Status Discipline

- Re-processing a document (new file version) must **delete before it re-creates**: wipe existing Pinecone vectors (`delete_document_vectors`) and existing `KnowledgeChunk` rows for that document before upserting/inserting new ones. Never append-only across re-processing runs.
- Follow the existing status state machine (`IngestionStatus`: `PENDING → PROCESSING → INDEXED` or `FAILED`) exactly — set `PROCESSING` before any extraction/embedding work starts, and always land on a terminal state (`INDEXED` or `FAILED`) even on partial failure. Wrap the whole pipeline function in `try/except/finally`, with `finally` cleaning up any downloaded temp file regardless of outcome.
- A document delete (soft-delete) should also clean up its `KnowledgeChunk` rows and Pinecone vectors if you're touching this area — the current delete route only flips `is_active` and leaves both behind (a known gap, not an intentional design).

---

# Background Execution

- Processing currently runs via FastAPI `BackgroundTasks`, not through the (currently inert) Arq queue — see the `fastapi-backend` skill's background-work section before adding a new trigger path. Don't assume `tasks/arq_worker.py::knowledge_document_job` will run just because it's registered.

---

# Before Completing Any Ingestion Change

Verify

✓ New file types are registered through `extraction/factory.py`'s dispatch map, not special-cased elsewhere

✓ Chunk content stored/embedded is breadcrumb-prefixed

✓ Any new Pinecone metadata field is also handled at query time if it should be filterable

✓ Re-processing deletes existing vectors/chunk rows before writing new ones

✓ Status transitions cover both the success and failure terminal states

✓ Temp files are cleaned up in a `finally` block

✓ Embedding model changes are checked against the configured Pinecone index dimension

If any item is missing, the ingestion change is not complete.
