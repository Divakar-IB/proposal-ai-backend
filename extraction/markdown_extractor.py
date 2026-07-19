from pathlib import Path

from extraction.base import BaseExtractor, ExtractedDocument, ExtractedPage, ExtractionMethod


class MarkdownExtractor(BaseExtractor):
    """.md files are already the normalized output format — read through
    unchanged, no parsing needed."""

    def extract(self, file_path: str, source_filename: str) -> ExtractedDocument:
        markdown = Path(file_path).read_text(encoding="utf-8")
        page = ExtractedPage(page_number=1, markdown=markdown, extraction_method=ExtractionMethod.MARKDOWN)
        return ExtractedDocument(markdown=markdown, source_filename=source_filename, pages=[page])
