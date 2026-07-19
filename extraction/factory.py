from extraction.base import BaseExtractor, ExtractedDocument
from extraction.docx_extractor import DocxExtractor
from extraction.image_extractor import ImageExtractor
from extraction.markdown_extractor import MarkdownExtractor
from extraction.pdf_extractor import PDFExtractor

_EXTRACTORS: dict[str, type[BaseExtractor]] = {
    "pdf": PDFExtractor,
    "docx": DocxExtractor,
    "png": ImageExtractor,
    "jpg": ImageExtractor,
    "jpeg": ImageExtractor,
    "md": MarkdownExtractor,
}


def get_extractor(extension: str) -> BaseExtractor:
    extractor_cls = _EXTRACTORS.get(extension.lower().lstrip("."))
    if extractor_cls is None:
        raise ValueError(f"No extractor registered for extension '.{extension}'")
    return extractor_cls()


def run_extraction(file_path: str, source_filename: str, extension: str) -> ExtractedDocument:
    """Single entry point used identically by both the knowledge-document
    and requirement-document pipelines — all three formats converge here."""

    extractor = get_extractor(extension)
    return extractor.extract(file_path, source_filename)
