from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ExtractionMethod(str, Enum):
    PYMUPDF_TEXT = "pymupdf_text"
    PYMUPDF_OCR = "pymupdf_ocr"
    DOCX = "docx"
    IMAGE_OCR = "image_ocr"
    MARKDOWN = "markdown"


@dataclass
class ExtractedPage:
    """One page/section of normalized output, before pages are joined into a single document."""

    page_number: int
    markdown: str
    extraction_method: ExtractionMethod


@dataclass
class ExtractedDocument:
    """Unified output of every extractor: Markdown text + page/source metadata."""

    markdown: str
    source_filename: str
    pages: list[ExtractedPage] = field(default_factory=list)


class BaseExtractor(ABC):
    """Every format-specific extractor converges on ExtractedDocument."""

    @abstractmethod
    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        raise NotImplementedError
