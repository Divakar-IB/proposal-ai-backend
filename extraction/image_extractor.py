from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionError, ExtractionMethod
from extraction.ocr_engine import StructuredOCREngine
from utilities.logger import get_logger

logger = get_logger(__name__)


class ImageExtractor(BaseExtractor):
    """Standalone image uploads (e.g. scanned requirement docs) go straight
    to PPStructureV3 — layout preserved, output normalized to Markdown."""

    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        try:
            result = StructuredOCREngine.run(file_path)
        except ExtractionError:
            raise
        except Exception as exc:
            logger.exception("OCR failed for image upload | file=%s", source_filename)
            raise ExtractionError(f"OCR failed for image '{source_filename}': {exc}") from exc

        page = ExtractedPage(
            page_number=1,
            markdown=result.markdown,
            extraction_method=ExtractionMethod.IMAGE_OCR,
            ocr_confidence=result.confidence,
            ocr_structured=result.structured,
        )
        return ExtractedDocument(markdown=result.markdown, source_filename=source_filename, pages=[page])
