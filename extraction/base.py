from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ExtractionMethod(str, Enum):
    PYMUPDF_TEXT = "pymupdf_text"
    PYMUPDF_OCR = "pymupdf_ocr"
    DOCX = "docx"
    IMAGE_OCR = "image_ocr"
    MARKDOWN = "markdown"


class ExtractionError(Exception):
    """Raised for any unrecoverable extraction/OCR failure (corrupt/encrypted
    file, undecodable image, engine failure) — callers translate this into a
    FAILED document status rather than letting a raw library exception surface."""


class OCRTimeoutError(ExtractionError):
    """Raised when a PPStructureV3 predict() call exceeds its configured timeout."""


@dataclass
class ExtractedPage:
    """One page/section of normalized output, before pages are joined into a single document."""

    page_number: int
    markdown: str
    extraction_method: ExtractionMethod
    # Populated only for OCR'd pages (extraction_method in {PYMUPDF_OCR, IMAGE_OCR}).
    # ocr_confidence is the page's mean text-recognition confidence (0..1).
    # ocr_structured is PPStructureV3's own structured result (layout blocks,
    # table HTML, bounding boxes) — kept so future reprocessing (e.g. smarter
    # chunking, table re-rendering) doesn't require re-running OCR.
    ocr_confidence: Optional[float] = None
    ocr_structured: Optional[dict[str, Any]] = None


@dataclass
class ExtractedDocument:
    """Unified output of every extractor: Markdown text + page/source metadata."""

    markdown: str
    source_filename: str
    pages: list[ExtractedPage] = field(default_factory=list)

    def to_page_records(self) -> list[dict[str, Any]]:
        """JSON-safe per-page snapshot for persistence (KnowledgeDocument/
        RequirementDocument.extracted_pages) — the durable record that lets a
        future feature (re-chunking, table re-rendering, confidence-based QA)
        reuse this document's OCR output without re-running OCR."""

        return [
            {
                "page_number": page.page_number,
                "extraction_method": page.extraction_method.value,
                "markdown": page.markdown,
                "ocr_confidence": page.ocr_confidence,
                "ocr_structured": page.ocr_structured,
            }
            for page in self.pages
        ]


class BaseExtractor(ABC):
    """Every format-specific extractor converges on ExtractedDocument."""

    @abstractmethod
    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        raise NotImplementedError
