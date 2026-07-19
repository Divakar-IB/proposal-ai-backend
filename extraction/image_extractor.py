from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionMethod
from extraction.ocr_engine import StructuredOCREngine


class ImageExtractor(BaseExtractor):
    """Standalone image uploads (e.g. scanned requirement docs) go straight
    to PPStructureV3 — layout preserved, output normalized to Markdown."""

    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        markdown = StructuredOCREngine.image_to_markdown(file_path)
        page = ExtractedPage(page_number=1, markdown=markdown, extraction_method=ExtractionMethod.IMAGE_OCR)
        return ExtractedDocument(markdown=markdown, source_filename=source_filename, pages=[page])
