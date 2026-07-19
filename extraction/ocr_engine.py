"""Shared PaddleOCR/PPStructureV3 wrapper used by both PDFExtractor (scanned pages)
and ImageExtractor (standalone image uploads)."""

from paddleocr import PPStructureV3

from utilities.logger import get_logger

logger = get_logger(__name__)


class StructuredOCREngine:
    """Lazily-initialized singleton — PPStructureV3 loads several models on first use."""

    _engine: PPStructureV3 | None = None

    @classmethod
    def get_engine(cls) -> PPStructureV3:
        if cls._engine is None:
            logger.info("initializing PPStructureV3 engine")
            cls._engine = PPStructureV3(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        return cls._engine

    @classmethod
    def image_to_markdown(cls, image_path: str) -> str:
        """Runs layout-aware OCR on a single image and returns Markdown
        (paragraphs/tables preserved via PPStructureV3's markdown output)."""

        engine = cls.get_engine()
        results = engine.predict(image_path)

        markdown_parts: list[str] = []
        for result in results:
            markdown_info = result.markdown
            text = markdown_info.get("markdown_texts") if isinstance(markdown_info, dict) else None
            if text:
                markdown_parts.append(text)

        return "\n\n".join(markdown_parts).strip()
