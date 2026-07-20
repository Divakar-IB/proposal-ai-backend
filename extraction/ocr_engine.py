"""Shared PaddleOCR/PPStructureV3 wrapper used by both PDFExtractor (scanned pages)
and ImageExtractor (standalone image uploads)."""

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from paddleocr import PPStructureV3

from config import config
from extraction.base import OCRTimeoutError
from extraction.image_preprocessing import preprocess_for_ocr
from utilities.logger import get_logger

logger = get_logger(__name__)

# Keys inside PPStructureV3's result.json payload that can carry embedded
# pixel/preview data rather than facts about the page — stripped before
# persistence so a document's extracted_pages column stays text/JSON-sized.
_BINARY_PAYLOAD_KEYS = {"img", "imgs_in_doc", "input_img"}


@dataclass
class OCRPageResult:
    """Everything a single page/image OCR call produces, kept together so
    callers can persist more than just the markdown string — layout, table
    HTML, bounding boxes, and confidence all come from the same predict() call."""

    markdown: str
    structured: dict[str, Any]
    confidence: Optional[float]


class StructuredOCREngine:
    """Lazily-initialized singleton — PPStructureV3 loads several models on first use."""

    _engine: Optional[PPStructureV3] = None
    _lock = threading.Lock()

    @classmethod
    def get_engine(cls) -> PPStructureV3:
        if cls._engine is None:
            with cls._lock:
                if cls._engine is None:
                    logger.info(
                        "initializing PPStructureV3 engine | orientation=%s unwarping=%s",
                        config.ocr.use_doc_orientation_classify, config.ocr.use_doc_unwarping,
                    )
                    cls._engine = PPStructureV3(
                        use_doc_orientation_classify=config.ocr.use_doc_orientation_classify,
                        use_doc_unwarping=config.ocr.use_doc_unwarping,
                    )
        return cls._engine

    @classmethod
    def run(cls, image_path: str) -> OCRPageResult:
        """Runs OCR on a single image/page (with preprocessing) and returns its full structured result."""
        return cls.run_batch([image_path])[0]

    @classmethod
    def run_batch(cls, image_paths: list[str]) -> list[OCRPageResult]:
        """Runs OCR over multiple images/pages in bounded-size batches — one
        predict() call per batch instead of one per page. If a batch call
        fails outright, falls back to processing that batch's pages one at a
        time so a single bad page doesn't cost the whole batch; a page that
        still fails in isolation is returned as an empty result rather than
        aborting the caller's document."""

        if not image_paths:
            return []

        processed_paths = [preprocess_for_ocr(path) for path in image_paths]
        results: list[OCRPageResult] = []
        batch_size = max(1, config.ocr.batch_size)

        try:
            for start in range(0, len(processed_paths), batch_size):
                batch = processed_paths[start:start + batch_size]
                try:
                    results.extend(cls._predict_with_timeout(batch))
                except Exception:
                    logger.exception("batched OCR call failed, retrying page-by-page | batch_size=%s", len(batch))
                    for single in batch:
                        try:
                            results.extend(cls._predict_with_timeout([single]))
                        except Exception:
                            logger.exception("OCR failed for a single page, marking it empty | path=%s", single)
                            results.append(OCRPageResult(markdown="", structured={}, confidence=None))
        finally:
            for original, processed in zip(image_paths, processed_paths):
                if processed != original:
                    Path(processed).unlink(missing_ok=True)

        return results

    @classmethod
    def _predict_with_timeout(cls, batch: list[str]) -> list[OCRPageResult]:
        engine = cls.get_engine()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(engine.predict, batch)
            try:
                raw_results = future.result(timeout=config.ocr.page_timeout_seconds)
            except FutureTimeoutError as exc:
                raise OCRTimeoutError(
                    f"OCR timed out after {config.ocr.page_timeout_seconds}s for a batch of {len(batch)} page(s)"
                ) from exc

        return [_to_page_result(result) for result in raw_results]


def _to_page_result(result: Any) -> OCRPageResult:
    markdown_info = result.markdown if hasattr(result, "markdown") else {}
    markdown = markdown_info.get("markdown_texts") if isinstance(markdown_info, dict) else None

    raw_json = result.json if hasattr(result, "json") else {}
    structured = raw_json.get("res", raw_json) if isinstance(raw_json, dict) else {}

    return OCRPageResult(
        markdown=(markdown or "").strip(),
        structured=_strip_binary_payload(structured),
        confidence=_mean_confidence(result),
    )


def _mean_confidence(result: Any) -> Optional[float]:
    ocr_res = result.get("overall_ocr_res") if hasattr(result, "get") else None
    scores = ocr_res.get("rec_scores") if isinstance(ocr_res, dict) else None
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def _strip_binary_payload(value: Any) -> Any:
    """Recursively drops keys carrying embedded pixel/image data and coerces
    numpy scalars/arrays to plain Python types, so the result can be written
    straight into a Postgres JSONB column."""

    if isinstance(value, dict):
        return {
            key: _strip_binary_payload(val)
            for key, val in value.items()
            if key not in _BINARY_PAYLOAD_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_binary_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "tolist"):  # numpy arrays
        return value.tolist()
    if hasattr(value, "item"):  # numpy scalars
        try:
            return value.item()
        except (ValueError, AttributeError):
            return str(value)
    return str(value)
