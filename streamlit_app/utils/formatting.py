"""Small formatting helpers shared across pages/components — status colors,
badges, relative timestamps. Kept dependency-free (just str/HTML building)
so components can import freely without cycles."""

from datetime import datetime, timezone
from typing import Optional

PROPOSAL_STATUS_META = {
    "inprogress": {"label": "In Progress", "color": "#6B7280", "bg": "#F3F4F6"},
    "generating": {"label": "Generating", "color": "#B45309", "bg": "#FEF3C7"},
    "review": {"label": "In Review", "color": "#6D28D9", "bg": "#EDE9FE"},
    "done": {"label": "Done", "color": "#15803D", "bg": "#DCFCE7"},
    "failed": {"label": "Failed", "color": "#B91C1C", "bg": "#FEE2E2"},
}

SECTION_STATUS_META = {
    "pending": {"label": "Pending", "color": "#6B7280", "bg": "#F3F4F6"},
    "drafting": {"label": "Drafting", "color": "#1D4ED8", "bg": "#DBEAFE"},
    "drafted": {"label": "Drafted", "color": "#0E7490", "bg": "#CFFAFE"},
    "needs_revision": {"label": "Needs Revision", "color": "#B45309", "bg": "#FEF3C7"},
    "approved": {"label": "Approved", "color": "#15803D", "bg": "#DCFCE7"},
}

DOCUMENT_STATUS_META = {
    "uploading": {"label": "Uploading", "color": "#6B7280", "bg": "#F3F4F6"},
    "extracting": {"label": "Extracting", "color": "#1D4ED8", "bg": "#DBEAFE"},
    "parsed": {"label": "Parsed", "color": "#15803D", "bg": "#DCFCE7"},
    "failed": {"label": "Failed", "color": "#B91C1C", "bg": "#FEE2E2"},
}


def _badge_html(value: Optional[str], meta_map: dict) -> str:
    key = (value or "").lower()
    meta = meta_map.get(key, {"label": (value or "Unknown").title(), "color": "#374151", "bg": "#F3F4F6"})
    return (
        f'<span style="background:{meta["bg"]};color:{meta["color"]};'
        f'padding:2px 10px;border-radius:999px;font-size:0.78rem;font-weight:600;'
        f'white-space:nowrap;">{meta["label"]}</span>'
    )


def proposal_status_badge(status: Optional[str]) -> str:
    return _badge_html(status, PROPOSAL_STATUS_META)


def section_status_badge(status: Optional[str]) -> str:
    return _badge_html(status, SECTION_STATUS_META)


def document_status_badge(status: Optional[str]) -> str:
    return _badge_html(status, DOCUMENT_STATUS_META)


def confidence_label(score: Optional[float]) -> str:
    if score is None:
        return "—"
    return f"{round(score * 100)}%"


def confidence_color(score: Optional[float]) -> str:
    if score is None:
        return "#6B7280"
    if score >= 0.7:
        return "#15803D"
    if score >= 0.4:
        return "#B45309"
    return "#B91C1C"


def time_ago(timestamp: Optional[str]) -> str:
    """Accepts an ISO timestamp string (as returned by the API) and renders
    a short relative label. Falls back to the raw value if unparsable."""
    if not timestamp:
        return "—"
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp

    now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
    delta = now - dt
    seconds = delta.total_seconds()

    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"
