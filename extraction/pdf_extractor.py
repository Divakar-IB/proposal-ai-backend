import tempfile
from pathlib import Path

import fitz  # PyMuPDF

from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionMethod
from extraction.heading_detector import LineFeatures, classify_heading
from extraction.ocr_engine import StructuredOCREngine
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

if __name__ == "__main__":
    ob1 = PDFExtractor()
    ob1.extract(
        file_path="/home/ib-40/Downloads/AI_Trade_Intelligence_Portal_RFP_2026.pdf",
        source_filename="sample.pdf",
    )