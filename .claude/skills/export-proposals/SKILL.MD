---
name: export-proposals
description: Use when creating or modifying proposal export — rendering templates, PDF/DOCX generation, or the download/email export endpoints.
---

# Export Proposals Skill

## Purpose

This skill governs turning a proposal's sections into a downloadable or emailable document: sections → Markdown → HTML → PDF/DOCX. See the `system-workflow` skill's `export-flow.md` reference for the full current-state narrative (file:line detail, what's live vs. dead). This file is the rulebook for extending it correctly.

Tech stack

- Jinja2 (HTML templates)
- WeasyPrint (HTML → PDF)
- Pypandoc (Markdown → HTML fragment, HTML → DOCX)
- SMTP (`utilities/email_service.py`) for the email-export path

---

# Templates

- The **only template registry actually used by rendering** is `rendering/html_templates.py`'s `HTML_TEMPLATES` map (`template_id → html file path`). Register any new export template there.
- `rendering/templates.py` (`PROPOSAL_TEMPLATES`, pairing per-template `pdf_css` with a Pandoc `--reference-doc` for DOCX) is **not wired into the live pipeline** — don't add a new template there expecting it to take effect. If you're intentionally reviving richer per-template DOCX styling, you must also update `rendering/renderer.py::render_docx_from_html` to actually pass the reference-doc to pypandoc — right now no `extra_args`/reference-doc is passed at all, so DOCX output uses Pandoc's plain defaults regardless of which HTML template was used.
- All visual styling for the live path must live inside the template's own embedded `<style>` block — neither `weasyprint.HTML(string=html).write_pdf()` nor the DOCX path receive any injected CSS from outside the template.
- `constants.EXPORT_TEMPLATES` (used only by `GET /proposal/templates` for S3-hosted preview thumbnails) and `rendering.html_templates.HTML_TEMPLATES` (the actual render targets) are two separately-maintained dicts. If you add, remove, or renumber a template, update **both** — nothing enforces they stay in sync.

---

# Rendering Pipeline

- Export always renders **live** from current `ProposalSection` rows (via `assemble_markdown` → `markdown_to_json` → `render_proposal_html`) — it does not read `Proposal.approved_markdown` or `Proposal.proposal_json`, even though both columns exist on the model. Don't "fix" this by reading those columns without first confirming with the review-workflow owner whether the approval/freeze feature they were meant for is actually being reintroduced (see `system-workflow`'s `review-workflow.md`) — right now they're permanently empty, so reading them would just break export.
- Reuse `_build_proposal_json`/`assemble_markdown`/`render_proposal_html` for any new export variant rather than re-deriving Markdown/HTML from sections a second way.

---

# Formats

- `ExportFormat` currently supports only `PDF` and `DOCX`. Adding a new format (e.g. HTML) means: add the enum value, add a branch in whatever selects the renderer, and reuse `render_proposal_html` directly for the HTML case — HTML is already produced internally as an intermediate stage, don't re-implement it.
- Any new binary format should follow the existing shape: a plain function taking rendered HTML (or JSON) and returning bytes, plus an entry in the content-type map (`services/proposal_export_service.py`'s `_CONTENT_TYPES`).

---

# Persistence

- **Nothing is persisted today** — rendered bytes are returned directly in the response (download) or streamed into the email send (email) and discarded. If you're adding persisted exports (e.g. an export history, or caching a rendered file):
  - Use the existing `S3PathBuilder.proposal_docx(user_id, proposal_id)` / `.proposal_pdf(...)` helpers (`utilities/s3_service.py`) — they're already correctly defined for exactly this purpose, just currently unused. Don't invent a new key scheme.
  - Update `Proposal.pdf_path`/`docx_path` via `update_proposal(...)` when you do persist a file — those columns exist and are already read out in response schemas, but nothing currently writes them.
  - Consider whether persisted exports should be recomputed on every request (current behavior) or cached until sections change — this is a deliberate product decision, not something to default silently.

---

# Status Side Effects

- Both current export routes (download and email) force `Proposal.status → DONE` on any successful render, unconditionally, regardless of prior status. Treat this as an intentional, existing behavior — preserve it for any new export variant unless there's a deliberate product decision to change it (e.g. "email export shouldn't mark done, only downloads should"). Don't silently drop or duplicate this side effect when adding new export code paths.
- There is no `exported_at` timestamp and no export-specific status enum — success/failure is only surfaced via the HTTP response code today. If you need export auditability, add an explicit field/table rather than overloading `Proposal.status`.

---

# Email

- Reuse `utilities/email_service.py`'s `send_email`/`EmailAttachment` pattern for any new email-triggering feature — it's shared with OTP and team-invite emails and is the only SMTP integration in the codebase. Don't write a second SMTP client.
- Keep the render-then-email sequence's error handling split: a render failure and a send failure are different failure modes and should raise distinct, clear errors (both currently surface as `502`, but with distinguishable messages) — don't collapse them into one generic error.

---

# Before Completing Any Export Change

Verify

✓ New templates are registered in `rendering/html_templates.py`, not `rendering/templates.py`

✓ `constants.EXPORT_TEMPLATES` and `HTML_TEMPLATES` stay in sync if templates changed

✓ Styling lives in the template file, not injected externally

✓ New export logic reuses `_build_proposal_json`/`assemble_markdown`/`render_proposal_html`

✓ Any persistence work uses the existing `S3PathBuilder` helpers and writes back `pdf_path`/`docx_path`

✓ The `status → DONE` side effect is preserved (or deliberately changed, not silently dropped)

✓ New email features reuse `utilities/email_service.py`

If any item is missing, the export change is not complete.
---

# Pre-Export Validation

Before generating or sending any document, always validate the rendered output as if a human reviewer were checking the final proposal.

## Document Quality Checklist

Verify the final rendered HTML/PDF/DOCX for the following:

### Structure

- All proposal sections are present in the expected order.
- No duplicated sections.
- No missing headings.
- Table of contents (if present) matches the document.
- Page breaks occur in appropriate locations.

### Formatting

- Headings use the correct hierarchy.
- Fonts, spacing, and alignment are consistent.
- Tables fit within page boundaries.
- Images, logos, and icons render correctly.
- Lists, bullets, and numbering are preserved.
- Code blocks (if any) render correctly.
- Links remain clickable where supported.

### Content

- No raw Markdown syntax remains (`#`, `*`, ````, etc.).
- No Jinja placeholders remain (`{{ }}`, `{% %}`).
- No "None", "null", "undefined", or empty placeholders appear.
- Variables are fully resolved.
- Special characters and Unicode render correctly.
- Escaped HTML is not visible.

### Layout

- Content is not clipped or overflowing.
- Long tables split correctly across pages.
- Headers and footers appear where expected.
- Margins are consistent.
- No unexpected blank pages.
- No orphan or widow headings where practical.

### Export Format

For PDF

- Every page renders successfully.
- Pagination is correct.
- Embedded fonts render correctly.
- Printable without layout issues.

For DOCX

- Headings remain editable.
- Tables remain editable.
- Images are embedded correctly.
- Paragraph spacing is preserved.
- Opening the document in Microsoft Word produces no repair warnings.

### File Integrity

- Output bytes are non-empty.
- MIME type matches the requested format.
- Filename extension matches the content.
- Generated document can be opened successfully.

### Error Handling

If validation fails:

- Do not return or email the document.
- Return a clear validation error describing what failed.
- Never silently generate a partially broken document.

The export pipeline should always prefer failing with a clear error over producing a corrupted or incomplete document.