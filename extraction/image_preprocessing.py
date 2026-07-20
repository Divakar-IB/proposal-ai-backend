"""Conditional image-quality preprocessing applied before a page/image is sent
to PPStructureV3. Every correction is gated on a cheap heuristic measured from
the image itself — unconditionally denoising, sharpening, or thresholding a
already-clean scan tends to *reduce* OCR accuracy, so each step only runs when
its corresponding defect is actually detected. Coarse page rotation (0/90/180/
270) and geometric page unwarping are intentionally left to PPStructureV3's
own doc-preprocessor sub-pipeline (see extraction/ocr_engine.py) — this module
only handles what that sub-pipeline does not: small-angle deskew, denoising,
contrast, sharpening, border removal, and resolution enhancement.
"""

import tempfile

import cv2
import numpy as np

from extraction.base import ExtractionError
from utilities.logger import get_logger

logger = get_logger(__name__)

# Below this shorter-side pixel count, glyphs are usually too small for
# reliable recognition — the image is upscaled toward this floor.
MIN_SHORT_SIDE_PX = 1200
# cv2.Laplacian variance below this looks blurry enough to warrant sharpening.
BLUR_VARIANCE_THRESHOLD = 120.0
# Grayscale std-dev below this indicates low contrast (faded scan/photocopy).
LOW_CONTRAST_STDDEV = 45.0
# Estimated skew below this is noise from the estimator, not real skew.
MIN_SKEW_DEGREES = 0.4
# Estimated skew above this is a coarse orientation issue, not skew — left to
# PPStructureV3's own orientation classifier instead of rotating blindly.
MAX_SKEW_DEGREES = 15.0
# Fraction of border pixels that must be near-black to treat it as a
# scanner/photocopier border rather than genuine page content.
BORDER_DARK_RATIO = 0.85


def preprocess_for_ocr(image_path: str) -> str:
    """Loads image_path, conditionally applies orientation-safe quality
    corrections, and returns a path to the (possibly new) processed image.
    Returns image_path unchanged if no correction was warranted — callers
    must only clean up the returned path when it differs from image_path."""

    image = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if image is None:
        raise ExtractionError(f"Could not decode image for OCR preprocessing: {image_path}")

    working = image
    changed = False

    for step in (
        _remove_scanner_border,
        _enhance_resolution,
        _deskew,
        _denoise_if_noisy,
        _enhance_contrast_if_flat,
        _sharpen_if_blurry,
        _adaptive_threshold_if_beneficial,
    ):
        result = step(working)
        if result is not None:
            working, changed = result, True

    if not changed:
        return image_path

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        out_path = tmp.name
    cv2.imwrite(out_path, working)
    logger.info("preprocessing applied before OCR | src=%s out=%s", image_path, out_path)
    return out_path


def _remove_scanner_border(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    border_px = max(2, min(h, w) // 100)
    edge_pixels = np.concatenate([
        gray[:border_px, :].ravel(),
        gray[-border_px:, :].ravel(),
        gray[:, :border_px].ravel(),
        gray[:, -border_px:].ravel(),
    ])
    if float(np.mean(edge_pixels < 40)) < BORDER_DARK_RATIO:
        return None  # no significant dark border

    _, binary = cv2.threshold(gray, 40, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    x, y, cw, ch = cv2.boundingRect(max(contours, key=cv2.contourArea))
    if cw < w * 0.5 or ch < h * 0.5:
        return None  # degenerate crop — leave the image untouched

    margin = border_px
    x0, y0 = max(0, x - margin), max(0, y - margin)
    x1, y1 = min(w, x + cw + margin), min(h, y + ch + margin)
    return image[y0:y1, x0:x1]


def _enhance_resolution(image: np.ndarray):
    h, w = image.shape[:2]
    short_side = min(h, w)
    if short_side >= MIN_SHORT_SIDE_PX:
        return None
    scale = MIN_SHORT_SIDE_PX / short_side
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)


def _deskew(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if coords.shape[0] < 100:
        return None  # not enough foreground pixels to estimate skew reliably

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    skew = -angle

    if abs(skew) < MIN_SKEW_DEGREES or abs(skew) > MAX_SKEW_DEGREES:
        return None  # noise, or a coarse rotation left to PPStructureV3

    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), skew, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _denoise_if_noisy(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    median = cv2.medianBlur(gray, 3)
    noise_level = float(np.std(gray.astype(np.int16) - median.astype(np.int16)))
    if noise_level < 6.0:
        return None
    return cv2.fastNlMeansDenoisingColored(image, None, h=7, hColor=7, templateWindowSize=7, searchWindowSize=21)


def _enhance_contrast_if_flat(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if float(np.std(gray)) >= LOW_CONTRAST_STDDEV:
        return None
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    lab = cv2.merge((clahe.apply(l_channel), a_channel, b_channel))
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _sharpen_if_blurry(image: np.ndarray):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if cv2.Laplacian(gray, cv2.CV_64F).var() >= BLUR_VARIANCE_THRESHOLD:
        return None
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=3)
    return cv2.addWeighted(image, 1.5, blurred, -0.5, 0)


def _adaptive_threshold_if_beneficial(image: np.ndarray):
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    if float(np.mean(hsv[:, :, 1])) >= 18.0:
        return None  # colour photo/diagram — thresholding would destroy signal

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
    hist = hist / (hist.sum() + 1e-9)
    # Most mass concentrated in the darkest/lightest quartiles is typical of a
    # clean text scan; anything else (mid-tone-heavy, e.g. a photo) is left alone.
    if (hist[:64].sum() + hist[192:].sum()) < 0.8:
        return None

    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
