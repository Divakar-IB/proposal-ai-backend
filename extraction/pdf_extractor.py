import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from config import config
from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionError, ExtractionMethod
from extraction.heading_detector import LineFeatures, classify_heading
from extraction.ocr_engine import StructuredOCREngine
from utilities.logger import get_logger

logger = get_logger(__name__)

# PyMuPDF's span flags carry a bold bit but no reliable underline signal (PDF
# underlines are usually drawn vector lines, not a font property), so
# underline_ratio is always 0.0 for the PDF path — bold/size/numbering/caps
# carry the detection here.
_BOLD_FLAG = 2 ** 4


class PDFExtractor(BaseExtractor):
    """PyMuPDF-based extraction with heading detection and per-page OCR fallback
    for scanned/image-heavy pages (routed to PPStructureV3)."""

    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        doc = self._open(file_path)

        try:
            body_size = self._estimate_body_font_size(doc)
            pages, scanned_jobs = self._prepare_pages(doc, body_size)
            self._run_ocr_jobs(pages, scanned_jobs)
        finally:
            doc.close()

        full_markdown = "\n\n".join(p.markdown for p in pages if p.markdown.strip())
        return ExtractedDocument(markdown=full_markdown, source_filename=source_filename, pages=pages)

    # ------------------------------------------------------------------
    # Opening — corrupted/encrypted PDF handling
    # ------------------------------------------------------------------

    def _open(self, file_path: str) -> "fitz.Document":
        try:
            doc = fitz.open(file_path)
        except Exception as exc:
            raise ExtractionError(f"Corrupted or unreadable PDF: {exc}") from exc

        if doc.is_encrypted:
            # Some PDFs are "encrypted" only to restrict editing and open with
            # a blank password — try that before giving up on the document.
            if not doc.authenticate(""):
                doc.close()
                raise ExtractionError("PDF is password-protected and cannot be processed")

        return doc

    # ------------------------------------------------------------------
    # Phase 1 — per-page triage: native text is extracted immediately;
    # scanned pages are rasterized and queued for a single batched OCR call.
    # Each page is fault-isolated so one bad page doesn't abort the rest of
    # the document — a failed page is recorded as empty and processing continues.
    # ------------------------------------------------------------------

    def _prepare_pages(
        self, doc: "fitz.Document", body_size: float
    ) -> tuple[list[ExtractedPage], list[tuple[int, str]]]:
        pages: list[ExtractedPage] = []
        scanned_jobs: list[tuple[int, str]] = []  # (index into `pages`, temp_image_path)

        for page_index in range(doc.page_count):
            page_number = page_index + 1
            try:
                page = doc[page_index]
                if self._is_scanned_page(page):
                    tmp_path = self._rasterize_page(page)
                    pages.append(ExtractedPage(
                        page_number=page_number, markdown="", extraction_method=ExtractionMethod.PYMUPDF_OCR,
                    ))
                    scanned_jobs.append((len(pages) - 1, tmp_path))
                else:
                    markdown = self._extract_page_text(page, body_size)
                    pages.append(ExtractedPage(
                        page_number=page_number, markdown=markdown, extraction_method=ExtractionMethod.PYMUPDF_TEXT,
                    ))
            except Exception:
                logger.exception("page extraction failed, continuing with remaining pages | page=%s", page_number)
                pages.append(ExtractedPage(
                    page_number=page_number, markdown="", extraction_method=ExtractionMethod.PYMUPDF_TEXT,
                ))

        return pages, scanned_jobs

    def _rasterize_page(self, page: "fitz.Page") -> str:
        pixmap = page.get_pixmap(dpi=config.ocr.dpi)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        pixmap.save(tmp_path)
        return tmp_path

    # ------------------------------------------------------------------
    # Phase 2 — one batched OCR call (StructuredOCREngine.run_batch chunks it
    # internally per config.ocr.batch_size) for every scanned page collected above.
    # ------------------------------------------------------------------

    def _run_ocr_jobs(self, pages: list[ExtractedPage], scanned_jobs: list[tuple[int, str]]) -> None:
        if not scanned_jobs:
            return

        temp_paths = [path for _, path in scanned_jobs]
        try:
            ocr_results = StructuredOCREngine.run_batch(temp_paths)
        finally:
            for path in temp_paths:
                Path(path).unlink(missing_ok=True)

        for (page_list_index, _), result in zip(scanned_jobs, ocr_results):
            page = pages[page_list_index]
            page.markdown = result.markdown
            page.ocr_confidence = result.confidence
            page.ocr_structured = result.structured
            logger.info(
                "page routed to OCR | page=%s chars=%s confidence=%s",
                page.page_number, len(result.markdown), result.confidence,
            )

    # ------------------------------------------------------------------
    # Scanned-page detection
    # ------------------------------------------------------------------

    def _is_scanned_page(self, page: "fitz.Page") -> bool:
        native_text = page.get_text().strip()
        if len(native_text) >= config.ocr.min_native_text_chars:
            image_coverage = self._image_coverage(page)
            if image_coverage < config.ocr.image_coverage_threshold:
                return False
        return True

    def _image_coverage(self, page: "fitz.Page") -> float:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return 0.0

        covered = 0.0
        for image in page.get_image_info():
            bbox = image.get("bbox")
            if not bbox:
                continue
            x0, y0, x1, y1 = bbox
            covered += max(0.0, x1 - x0) * max(0.0, y1 - y0)

        return min(covered / page_area, 1.0)

    def _estimate_body_font_size(self, doc: "fitz.Document") -> float:
        """Body text is assumed to be the most common font size across the
        document — headings are detected relative to this baseline."""

        size_counts: dict[float, int] = {}
        for page in doc:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = round(span.get("size", 0), 1)
                        text_len = len(span.get("text", "").strip())
                        if text_len:
                            size_counts[size] = size_counts.get(size, 0) + text_len

        if not size_counts:
            return 10.0
        return max(size_counts, key=lambda size: size_counts[size])

    def _extract_page_text(self, page: "fitz.Page", body_size: float) -> str:
        lines_markdown: list[str] = []

        for block in page.get_text("dict").get("blocks", []):
            if block.get("type") != 0:  # skip image blocks; handled via _is_scanned_page routing
                continue

            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue

                text = "".join(span.get("text", "") for span in spans).strip()
                if not text:
                    continue

                lines_markdown.append(self._render_line(text, spans, body_size))

        return "\n".join(lines_markdown)

    def _render_line(self, text: str, spans: list[dict], body_size: float) -> str:
        total_chars = sum(len(span.get("text", "")) for span in spans)
        bold_chars = sum(
            len(span.get("text", "")) for span in spans if span.get("flags", 0) & _BOLD_FLAG
        )
        max_size = max((span.get("size", body_size) for span in spans), default=body_size)

        prefix = classify_heading(LineFeatures(
            text=text,
            size=max_size,
            body_size=body_size,
            bold_ratio=bold_chars / total_chars if total_chars else 0.0,
        ))
        return f"{prefix} {text}" if prefix else text
