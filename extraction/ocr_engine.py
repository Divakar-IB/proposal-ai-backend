"""Shared PaddleOCR/PPStructureV3 wrapper used by both PDFExtractor (scanned pages)
and ImageExtractor (standalone image uploads)."""

from typing import TYPE_CHECKING, Optional

from utilities.logger import get_logger

if TYPE_CHECKING:
    from paddleocr import PPStructureV3

logger = get_logger(__name__)


class StructuredOCREngine:
    """Lazily-initialized singleton — PPStructureV3 loads several models on first use."""

    _engine: Optional["PPStructureV3"] = None

    @classmethod
    def get_engine(cls) -> "PPStructureV3":
        # Imported here, not at module scope. `paddleocr` pulls in paddlex,
        # paddlepaddle, pandas and OpenBLAS, which together commit ~900MB —
        # over 80% of the whole application's import footprint. This module is
        # reachable from `extraction/factory.py`, so a module-level import made
        # every process that touches extraction (the API server, the test
        # suite, an Alembic run) pay that cost at startup, even though OCR only
        # ever runs for a scanned PDF page or an uploaded image. On a machine
        # near its Windows commit limit that allocation is what fails, and it
        # fails as an opaque "the paging file is too small" DLL load error
        # during `import main` rather than anywhere near the OCR code.
        #
        # Nothing outside this method needs the symbol: both call sites go
        # through StructuredOCREngine, and the annotations above are strings
        # resolved only by type checkers.
        if cls._engine is None:
            from paddleocr import PPStructureV3

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
        # print("\n\n".join(markdown_parts).strip())
        return "\n\n".join(markdown_parts).strip()
