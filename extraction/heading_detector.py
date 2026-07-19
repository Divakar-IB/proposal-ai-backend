import re
from dataclasses import dataclass
from typing import Optional

# Matches common section-numbering conventions across real-world documents:
# "1.", "1.1", "1.2.3.4", "(1)", "1)", "a)", "A.", "IV.", "Section 2", "Chapter 3:".
_NUMBERING_PATTERN = re.compile(
    r"^\s*("
    r"\d+(\.\d+){0,4}\.?"
    r"|\(\d+\)"
    r"|\d+\)"
    r"|[A-Za-z]\)"
    r"|[A-Za-z]\."
    r"|[IVXLCDM]+\."
    r"|(Section|Chapter|Article|Phase|Part|Appendix)\s+\d+[:.]?"
    r")(\s|$)",
    re.IGNORECASE,
)
_NUMBERING_DEPTH_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+){0,4})\.?\s")

# Size deltas are relative to the document's own body-text baseline, not
# absolute point values — this is what lets one set of thresholds generalize
# across documents with wildly different base font sizes.
SIZE_DELTA_STRONG = 4.0
SIZE_DELTA_WEAK = 1.5
MAX_HEADING_WORDS = 18
SCORE_THRESHOLD = 3.0


@dataclass
class LineFeatures:
    text: str
    size: float
    body_size: float
    bold_ratio: float = 0.0       # fraction of the line's characters that are bold, 0..1
    underline_ratio: float = 0.0  # fraction of the line's characters that are underlined, 0..1


def classify_heading(features: LineFeatures) -> Optional[str]:
    """Scores a line/paragraph against multiple independent heading signals —
    size, bold, underline, numbering, all-caps, length — instead of relying
    on any single one. Returns a Markdown heading prefix ("#", "##", "###")
    or None. Used identically by PDFExtractor and DocxExtractor so heading
    detection doesn't diverge between formats."""

    text = features.text.strip()
    if not text:
        return None

    word_count = len(text.split())
    if word_count > MAX_HEADING_WORDS:
        return None

    delta = features.size - features.body_size
    is_numbered = bool(_NUMBERING_PATTERN.match(text))
    is_all_caps = text.isupper() and any(c.isalpha() for c in text)
    ends_with_sentence_punct = text.rstrip().endswith((".", ",", ";")) and not is_numbered

    score = 0.0
    if delta >= SIZE_DELTA_STRONG:
        score += 3.0
    elif delta >= SIZE_DELTA_WEAK:
        score += 1.5
    elif delta > 0:
        score += 0.5

    score += 2.0 * features.bold_ratio
    score += 1.0 * features.underline_ratio
    if is_numbered:
        score += 2.0
    if is_all_caps:
        score += 1.0
    if word_count <= 6:
        score += 0.5
    if ends_with_sentence_punct:
        score -= 2.0
    if word_count > 12:
        score -= 1.0

    if score < SCORE_THRESHOLD:
        return None

    return "#" * _heading_level(text, delta, is_numbered)


def _heading_level(text: str, delta: float, is_numbered: bool) -> int:
    if is_numbered:
        depth_match = _NUMBERING_DEPTH_PATTERN.match(text)
        if depth_match:
            depth = depth_match.group(1).count(".") + 1
            return min(depth, 3)

    if delta >= SIZE_DELTA_STRONG * 1.5:
        return 1
    if delta >= SIZE_DELTA_STRONG:
        return 2
    if delta >= SIZE_DELTA_WEAK:
        return 2
    return 3
