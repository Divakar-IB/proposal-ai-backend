# Export Flow

## 1. Entry points

Both endpoints live in `router/proposals.py` and were split apart in commit `b05c458` ("Correction in export proposal api, downloading and send via email files are segregated."). Before that, a single endpoint took an optional `email` field and did both in one call.

- **Download** — `POST /proposal/{proposal_id}/export`, body `ProposalExportRequest` (`schemas/proposal.py`: `template_id: int`, `format: ExportFormat`). Always returns rendered bytes as a raw `Response` with `Content-Disposition: attachment`. Never touches email.
- **Email** — `POST /proposal/{proposal_id}/export/email`, body `ProposalExportEmailRequest` (adds `email: EmailStr`). Renders the same way, then calls `email_rendered_proposal(...)`, returns `ProposalExportEmailResponse` (`proposal_id`, `template_id`, `format`, `sent_to`) — no binary in the response.
- **Template listing** — `GET /proposal/templates` (registered before `/{proposal_id}` routes to avoid path-matching collision). Returns entries from the hardcoded `constants.EXPORT_TEMPLATES` (4 entries: Modern/Minimal/Corporate/Executive), with `preview_url` generated fresh per request via a presigned S3 URL. **This template id space is separate from** the actual rendering templates in `rendering/html_templates.py` — see §2 caveat; whether the frontend is expected to reuse the same `template_id` across both is not verified in code.

**Formats supported:** only PDF and DOCX (`ExportFormat` enum). No plain-HTML export endpoint, even though HTML is an internal intermediate stage.

## 2. Rendering pipeline (sections → Markdown → JSON → HTML → PDF/DOCX)

Orchestrated by `services/proposal_export_service.py::render_proposal_document`:

1. **Fetch proposal** (`is_active=True`); 404 if missing; 409 if `proposal.sections` is empty.
2. **Validate `template_id`** against `rendering/html_templates.py`'s registry; 404 if unregistered.
3. **Sections → Markdown → JSON** — `_build_proposal_json` builds `{title, content, order_index}` per section, calls `assemble_markdown(proposal.title, sections)` then `markdown_to_json(markdown)`. Docstring explicitly notes this is built **live from current section rows**, not from `proposal.approved_markdown` or the frozen `proposal.proposal_json` column — both exist on the model but are bypassed here, since the approval/freeze flow isn't wired up (see review-workflow.md).
4. **JSON → HTML** (`rendering/html_renderer.py::render_proposal_html`):
   - Resolves the template file: `1→html/template_1.html`, `2→html/minimal.html`, `3→html/corporate_preview.html`, `4→html/executive_preview.html` (`rendering/html_templates.py`).
   - Each section's Markdown `content` is pre-converted to an HTML fragment via `pypandoc.convert_text(content, "html", format="md")`.
   - Jinja2 renders the template with `proposal_title`, `client_name`, `reference=f"PROP-{proposal_id}"`, `generated_date` (today), `sections=[{title, content_html}, ...]`.
   - All visual styling lives in a `<style>` block embedded directly in each `html/template_N.html` — no separate CSS asset for this path.
5. **HTML → PDF or DOCX** (`rendering/renderer.py`):
   - PDF: `weasyprint.HTML(string=html).write_pdf()` — no extra CSS injected; relies entirely on the template's embedded styles.
   - DOCX: `pypandoc.convert_text(html, "docx", format="html", outputfile=tmp_path)`, written to a tempfile, read back, then deleted. **No `--reference-doc`/extra_args passed** — Pandoc's default DOCX styles are used, and Pandoc's HTML→DOCX reader only maps a subset of CSS (headings, bold/italic, tables, lists), so DOCX output is visually plainer than the PDF for the same template.
6. **Status side-effect + filename**: if `proposal.status != DONE`, sets `status=DONE` (unconditionally, regardless of prior status or whether this was a download or email). Filename = `sanitize_filename(f"{proposal.title}.{format}")`. Content-type from a fixed map (PDF→`application/pdf`, DOCX→`application/vnd.openxmlformats-officedocument.wordprocessingml.document`).

**A second, unused template system exists:** `rendering/templates.py` defines `PROPOSAL_TEMPLATES` (ids 1-4: Classic Serif/Modern Blue/Minimal Mono/Corporate Bold), pairing inline `pdf_css` strings with `docx_reference_path` pointing at generated `.docx` files under `rendering/assets/docx_templates/`. Nothing in `services/proposal_export_service.py`, `rendering/renderer.py`, or `rendering/html_renderer.py` imports from this module or passes a reference-doc to pypandoc — it's dead/legacy code, not part of the live pipeline.

## 3. Storage

**No S3 upload occurs anywhere in the export path.** `proposal_export_service.py` doesn't import `utilities.s3_service` at all — rendered bytes are returned directly in the HTTP response (download) or streamed straight into the email send (email endpoint) and then discarded. Nothing is persisted.

Evidence this was once intended: `S3PathBuilder.proposal_docx(user_id, proposal_id)` → `output/proposals/{user_id}/{proposal_id}/proposal.docx` and `.proposal_pdf(...)` → `.../proposal.pdf` both exist in `utilities/s3_service.py`, but neither is ever called anywhere in the repo.

`Proposal.pdf_path` (added by migration `d7e8f9a0b1c2`) is a `Text` column intended to record where an export landed. It's read out in response schemas but **never written** — no `pdf_path=` assignment exists in any `update_proposal(...)` call. It is always `NULL`.

There is no export-history/record table and no export-specific CRUD functions. The only DB effect of an export call is the `status → DONE` transition (§2 step 6).

`ProposalExportResponse` (`schemas/proposal.py`, with `markdown_url`/`docx_url`/`pdf_url` fields suggesting a persisted-and-linked design) is defined but not actually used as the response model of either export route — both routes return something else. Also vestigial.

## 4. Email flow

- **Trigger:** `POST /{proposal_id}/export/email` only — purely user-initiated, no automatic/background trigger.
- **Flow:** router calls `render_proposal_document(...)` (rendered fresh, nothing reused from storage since nothing is stored) → `email_rendered_proposal(email, proposal, content, filename, content_type)`.
- **Attachment:** the exact rendered bytes (PDF or DOCX per requested format), wrapped in an `EmailAttachment` named tuple.
- **Sending service:** plain **SMTP** via stdlib `smtplib` — no SES/SendGrid/third-party API. `send_proposal_export_email(...)` (`utilities/email_service.py`) builds subject `"Proposal Document - {proposal_title}"` and a fixed plaintext body, calls the generic `send_email` which runs `_send_email_sync` in a thread via `asyncio.to_thread`. Builds an `EmailMessage`, attaches the file (maintype/subtype split from content-type), sends via `smtplib.SMTP(config.smtp.host, config.smtp.port)` with optional `starttls()`/`login()` using `config.smtp.*` settings.
- **Error handling:** both render and email steps catch exceptions and raise `HTTPException(502, ...)`.
- This SMTP utility is shared with two other, unrelated email templates in the same file: OTP emails and team-invite emails — it's a single-purpose SMTP module, not export-specific infrastructure.

## 5. Status tracking related to export

- `Proposal.status → DONE` is the only export-adjacent status effect, pushed unconditionally on any successful render (download or email alike), regardless of prior status.
- **No `exported_at` timestamp** exists on `Proposal` — no such column.
- **No export-specific status enum** (e.g. "exported"/"export_failed") — success/failure is only surfaced via the HTTP response code (200 vs. 502/404/409), never persisted.
- `Proposal.pdf_path` exists as a column but is dead (§3), so it can't be used as an export-tracking signal today.

## Summary of gaps

- Export always renders live from current `ProposalSection` rows, never from the frozen `approved_markdown`/`proposal_json` snapshot columns that already exist on the model — both are explicitly flagged in the code as pending an approval-gate wire-up (see review-workflow.md).
- `rendering/templates.py` (per-template `pdf_css` + Pandoc reference-doc DOCX styling) and its four generated `.docx` assets are unreferenced by the live rendering code.
- No S3 persistence of exported files despite `S3PathBuilder.proposal_docx`/`proposal_pdf` existing for exactly that purpose.
- `Proposal.pdf_path` and `ProposalExportResponse` (`markdown_url`/`docx_url`/`pdf_url`) both look like remnants of a previously-planned persisted-export design that was never finished.
- `constants.EXPORT_TEMPLATES` (S3 preview thumbnails, used by `GET /proposal/templates`) and `rendering.html_templates.HTML_TEMPLATES` (actual Jinja render targets) are separate id-keyed dicts maintained independently — whether their ids are meant to stay in sync is unclear from the code.
