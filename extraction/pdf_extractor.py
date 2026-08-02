import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionMethod
from extraction.heading_detector import LineFeatures, classify_heading
from extraction.ocr_engine import StructuredOCREngine
from extraction.table_markdown import rows_to_markdown
from utilities.logger import get_logger

logger = get_logger(__name__)

# A page whose native text layer has fewer than this many characters is treated
# as scanned/image-only and routed to OCR instead of the PyMuPDF text layer.
MIN_NATIVE_TEXT_CHARS = 40
# Pages where images cover more than this fraction of the page area are also
# treated as scanned, even if a thin text layer is present (e.g. a caption).
IMAGE_COVERAGE_THRESHOLD = 0.6
# PyMuPDF's span flags carry a bold bit but no reliable underline signal (PDF
# underlines are usually drawn vector lines, not a font property), so
# underline_ratio is always 0.0 for the PDF path — bold/size/numbering/caps
# carry the detection here.
_BOLD_FLAG = 2 ** 4


class PDFExtractor(BaseExtractor):
    """PyMuPDF-based extraction with heading detection and per-page OCR fallback
    for scanned/image-heavy pages (routed to PPStructureV3)."""

    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        doc = fitz.open(file_path)
        pages: list[ExtractedPage] = []

        try:
            body_size = self._estimate_body_font_size(doc)

            for page_index in range(doc.page_count):
                page = doc[page_index]
                page_number = page_index + 1

                if self._is_scanned_page(page):
                    markdown = self._extract_page_via_ocr(page)
                    method = ExtractionMethod.PYMUPDF_OCR
                else:
                    markdown = self._extract_page_text(page, body_size)
                    method = ExtractionMethod.PYMUPDF_TEXT

                pages.append(ExtractedPage(
                    page_number=page_number,
                    markdown=markdown,
                    extraction_method=method,
                ))
        finally:
            doc.close()

        full_markdown = "\n\n".join(p.markdown for p in pages if p.markdown.strip())
        return ExtractedDocument(markdown=full_markdown, source_filename=source_filename, pages=pages)

    # ------------------------------------------------------------------
    # Scanned-page detection
    # ------------------------------------------------------------------

    def _is_scanned_page(self, page: "fitz.Page") -> bool:
        native_text = page.get_text().strip()
        if len(native_text) >= MIN_NATIVE_TEXT_CHARS:
            image_coverage = self._image_coverage(page)
            if image_coverage < IMAGE_COVERAGE_THRESHOLD:
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
        """Renders a text-layer page to Markdown, emitting any detected tables
        as Markdown tables rather than as loose lines.

        Without the table pass a table's cells arrive as a flat stream of text
        lines and the row/column association is lost entirely — which then gets
        embedded and pasted into drafting prompts as meaningless runs of
        numbers. Table regions are therefore rendered separately and their
        lines excluded from the prose pass so nothing is duplicated. Items are
        re-sorted by vertical position to preserve reading order.
        """

        tables = self._find_tables(page)

        # (sort_key, markdown) so tables and prose can be interleaved in
        # reading order regardless of which pass produced them.
        items: list[tuple[float, float, str]] = []
        table_rects: list["fitz.Rect"] = []

        for rect, markdown in tables:
            table_rects.append(rect)
            items.append((rect.y0, rect.x0, markdown))

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

                line_rect = fitz.Rect(line["bbox"])
                if any(self._mostly_inside(line_rect, rect) for rect in table_rects):
                    continue  # already covered by the rendered table

                items.append((line_rect.y0, line_rect.x0, self._render_line(text, spans, body_size)))

        items.sort(key=lambda item: (round(item[0], 1), item[1]))
        return "\n".join(markdown for _, _, markdown in items)

    def _find_tables(self, page: "fitz.Page") -> list[tuple["fitz.Rect", str]]:
        """Detected tables as (bounding box, Markdown). Table detection is
        best-effort — a PDF with no ruling lines may yield nothing, in which
        case the page simply falls back to the prose-only behaviour."""

        try:
            finder = page.find_tables()
        except Exception:
            logger.exception("table detection failed | page=%s", page.number + 1)
            return []

        found: list[tuple["fitz.Rect", str]] = []
        for table in getattr(finder, "tables", []):
            try:
                # min_rows=2: a single detected row is nearly always a false
                # positive (a boxed callout), and rendering it as a table would
                # strip it of its prose formatting for no gain.
                markdown = rows_to_markdown(table.extract(), min_rows=2)
                if markdown:
                    found.append((fitz.Rect(table.bbox), markdown))
            except Exception:
                logger.exception("table render failed | page=%s", page.number + 1)

        if found:
            logger.info("tables extracted | page=%s count=%s", page.number + 1, len(found))
        return found

    @staticmethod
    def _mostly_inside(line_rect: "fitz.Rect", table_rect: "fitz.Rect", threshold: float = 0.5) -> bool:
        """True when most of a text line sits inside a table's bounds. Uses an
        overlap ratio rather than strict containment because a detected table
        box is often a pixel or two tighter than the glyphs it holds."""

        overlap = line_rect & table_rect
        if overlap.is_empty:
            return False
        line_area = line_rect.get_area()
        if line_area <= 0:
            return True
        return overlap.get_area() / line_area >= threshold

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

    # ------------------------------------------------------------------
    # OCR fallback path — scanned/image-heavy pages
    # ------------------------------------------------------------------

    def _extract_page_via_ocr(self, page: "fitz.Page") -> str:
        pixmap = page.get_pixmap(dpi=200)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            pixmap.save(tmp_path)
            markdown = StructuredOCREngine.image_to_markdown(tmp_path)
            logger.info("page routed to OCR | page=%s chars=%s", page.number + 1, len(markdown))
            return markdown
        finally:
            Path(tmp_path).unlink(missing_ok=True)