---
name: proposal-generation
description: Use when creating or modifying the proposal generation pipeline — section definitions, retrieval, drafting prompts, generation modes, or the SSE streaming endpoint.
---

# Proposal Generation Skill

## Purpose

This skill governs the section-by-section proposal drafting pipeline: combining requirement-document context with (optional) knowledge-base retrieval, streaming LLM-drafted sections over SSE, and persisting them. See the `system-workflow` skill's `proposal-generation-flow.md` reference for the full current-state narrative (file:line detail, what's live vs. dead). This file is the rulebook for extending it correctly.

Tech stack

- `GroqChatClient` (`llm/chat_client.py`) — OpenAI-compatible client against Groq (`openai/gpt-oss-120b`)
- Pinecone retrieval via `vectorstore/knowledge_store.py`
- SSE streaming (see the `fastapi-backend` skill's streaming section)

---

# Adding or Changing a Section

- Sections are entirely data-driven from `SECTION_DEFINITIONS` (`generation/sections.py`) — adding a new section means adding an entry there (`section_key`, `title`, `query_fields`, optional `outline`); no changes are needed in `generation/proposal_generator.py`'s loop itself.
- `query_fields` must reference **actual field names** on `RequirementsSchema` (`requirements_parsing/schema.py`). A typo doesn't raise an error — it silently yields no matched values for that section's retrieval query. Verify new/changed `query_fields` against the schema, and test that retrieval actually returns something for a section that's supposed to use knowledge-base content.
- If a section needs enforced subsections, use `outline` (rendered via `build_outline_instruction`) rather than hardcoding heading text into the drafting prompt — keep the "list of headings in order" contract intact so the instruction-building logic keeps working for every section.
- Section order is the literal order of `SECTION_DEFINITIONS` — reordering the list reorders the generated proposal.

---

# Prompts

- The prompts actually used for drafting live in `prompts/proposal_generation.py` (draft) and `prompts/proposal_review.py` (quality check). **`generation/prompts.py` is dead code** — do not add new prompt content there; if you're doing cleanup work in this area, either remove it or migrate anything it's still supplying (e.g. `WORDS_PER_PAGE`, currently imported from there into `generation/proposal_generator.py`) to a proper home first.
- Preserve the instruction that a drafted section returns **body content only, no repeated section heading** — `assemble_markdown` adds the `## {title}` heading itself; if the LLM also emits one, the assembled document gets duplicate headings.
- Preserve the `GAP:` convention (flag missing *client requirement* information, not missing knowledge-base context) — downstream consumers may rely on `GAP:` lines to signal review is needed; don't repurpose that marker for a different meaning.

---

# Retrieval

- Retrieval must stay gated behind `generation_mode == KNOWLEDGE_AUGMENTED` **and** a cheap "does at least one knowledge chunk exist" check (`has_any_knowledge_chunks`) before touching Pinecone — this avoids a wasted embed+query call on every section when the knowledge base is empty. Keep this short-circuit if you touch `retrieve_chunks_for_section`.
- Retrieval is scoped by `category_ids` on the `Proposal` row, but that field is **never actually set** by any current code path — it's always effectively unfiltered. If you rely on category-scoped retrieval, you must also implement the code that sets `Proposal.category_ids` somewhere (e.g. proposal/requirement-doc creation) — don't assume it already works because the filtering code exists.
- `top_k` for per-section retrieval (`TOP_K_SECTION_CHUNKS`) is a shared constant — changing it changes context size for every section uniformly; if only one section needs more/fewer chunks, override per-section rather than globally.

---

# Streaming

- Keep `draft_one_section_stream` compatible with the SSE contract in `generate_proposal_stream` — each yielded delta must be plain text appended to the running section content, re-emitted as a `section_chunk` event. Don't switch to a tool-calling/structured-output completion for the drafting call — `GroqChatClient.stream_complete` explicitly doesn't support forced tool calls alongside streaming ("streaming + forced tool calls don't mix cleanly").
- On any exception mid-generation, the pipeline must both persist a terminal `FAILED` status (with `error_message`) **and** yield an `error` SSE event — don't let one happen without the other, or the client and the DB state will disagree about what happened.

---

# Quality Check / Regeneration

- `run_quality_check`/`decide_section_status` (`generation/nodes.py`) are fully implemented but **not called anywhere in the live `/proposal/generate` stream** — every section there is persisted directly as `APPROVED` with no gate. If you want a quality gate in the main generation flow, you must explicitly add the call inside `generate_proposal_stream`'s per-section loop; it will not happen automatically just because the helper functions exist.
- `services/proposal_review_service.py::regenerate_section` already wires the full draft → quality-check → decide-status sequence for single-section regeneration, but currently has no router endpoint exposing it (see the `system-workflow` skill's `review-workflow.md`). Before building a new "regenerate this section" feature from scratch, check whether re-exposing this existing function is enough.

---

# Multi-Document Proposals

- Any change to how requirement documents are combined for generation must go through `generation/requirement_context.py::build_combined_requirements_json` — don't hardcode "use the first/only document" assumptions anywhere in the drafting path, since a proposal can have multiple requirement documents attached.
- `build_combined_summary` exists but is currently unused by drafting (summaries are UI-only, structured `parsed_data` is what actually grounds the LLM). Don't assume changing `.summary` content affects generated output — it doesn't, today.

---

# Status Transitions

- Generation owns `INPROGRESS → GENERATING → REVIEW` (success) or `→ FAILED` (error) on the `Proposal.status` enum. Don't introduce a new `ProposalStatus` value without also: updating the enum in `database/db_enum.py`, writing an Alembic migration (see the `database` skill), and checking `set_proposal_status`'s rank ordering so forward-only transition logic still makes sense with the new value inserted at the correct position.

---

# Before Completing Any Generation Change

Verify

✓ New/changed sections use `SECTION_DEFINITIONS`, not special-cased loop logic

✓ `query_fields` match real `RequirementsSchema` field names

✓ Drafting prompt still emits body-only content (no duplicate headings)

✓ Retrieval keeps the `has_any_knowledge_chunks` short-circuit

✓ Streaming and failure paths keep DB state and SSE events in agreement

✓ Multi-document proposals still work (no first-document-only assumptions)

✓ Any new status value has both an enum change and a migration

If any item is missing, the generation change is not complete.
