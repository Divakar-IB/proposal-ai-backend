import streamlit as st

from services.api_client import APIError, ProposalAPIClient
from services.auth import current_role, get_api_client, logout
from utils.activity import get_activities
from utils.formatting import confidence_color, confidence_label
from config.settings import api_settings

WIZARD_STEPS = [
    ("upload", "Upload Requirements"),
    ("processing", "Processing"),
    ("review", "Review & Refine"),
    ("export", "Export"),
]


@st.cache_data(ttl=20, show_spinner=False)
def _check_backend_health(_client: ProposalAPIClient) -> bool:
    try:
        _client.health_check()
        return True
    except APIError:
        return False


def _render_step_track(current_stage: str) -> None:
    stage_keys = [key for key, _ in WIZARD_STEPS]
    current_index = stage_keys.index(current_stage) if current_stage in stage_keys else -1

    rows = []
    for index, (key, label) in enumerate(WIZARD_STEPS):
        if current_index == -1:
            css_class, icon = "step-pending", "○"
        elif index < current_index:
            css_class, icon = "step-done", "✓"
        elif index == current_index:
            css_class, icon = "step-current", "●"
        else:
            css_class, icon = "step-pending", "○"
        rows.append(f'<div class="step-item {css_class}">{icon}&nbsp;&nbsp;{label}</div>')

    st.markdown(f'<div class="step-track">{"".join(rows)}</div>', unsafe_allow_html=True)


def _render_project_info() -> None:
    proposal = st.session_state.get("proposal")
    requirement_document = st.session_state.get("requirement_document")

    title = proposal.get("title") if proposal else (requirement_document or {}).get("proposal_name")
    client_name = proposal.get("client_name") if proposal else (requirement_document or {}).get("client_name")

    if not title and not client_name:
        st.markdown('<div class="app-card-subtle">No active proposal yet.</div>', unsafe_allow_html=True)
        return

    st.markdown(
        f"""
        <div class="app-card">
            <div class="app-card-title">📌 {title or "Untitled proposal"}</div>
            <div class="app-card-subtle">Client: {client_name or "—"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _section_stats() -> dict:
    proposal = st.session_state.get("proposal")
    sections = (proposal or {}).get("sections") or []
    total = len(sections)
    generated = sum(1 for s in sections if s.get("status") != "pending")
    approved = sum(1 for s in sections if s.get("status") == "approved")
    needs_review = sum(1 for s in sections if s.get("review_flag"))
    scored = [s["confidence_score"] for s in sections if s.get("confidence_score") is not None]
    avg_confidence = (sum(scored) / len(scored)) if scored else None
    return {
        "total": total,
        "generated": generated,
        "approved": approved,
        "needs_review": needs_review,
        "avg_confidence": avg_confidence,
    }


def _render_progress() -> None:
    stats = _section_stats()
    if stats["total"] == 0:
        st.markdown('<div class="app-card-subtle">Progress appears once generation starts.</div>', unsafe_allow_html=True)
        return

    st.progress(stats["approved"] / stats["total"] if stats["total"] else 0)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(
            f"""<div class="stat-tile"><div class="stat-value">{stats['generated']}/{stats['total']}</div>
            <div class="stat-label">Sections Generated</div></div>""",
            unsafe_allow_html=True,
        )
    with col2:
        color = confidence_color(stats["avg_confidence"])
        st.markdown(
            f"""<div class="stat-tile"><div class="stat-value" style="color:{color}">
            {confidence_label(stats['avg_confidence'])}</div>
            <div class="stat-label">Avg. Confidence</div></div>""",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="app-card" style="margin-top:0.6rem;">
            <div class="app-card-subtle">✅ Approved: <b>{stats['approved']}</b>
            &nbsp;·&nbsp; 🚩 Needs review: <b>{stats['needs_review']}</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_activities() -> None:
    activities = get_activities()
    if not activities:
        st.markdown('<div class="app-card-subtle">No activity yet this session.</div>', unsafe_allow_html=True)
        return

    items = "".join(
        f'<div class="activity-item">{a["icon"]}&nbsp; {a["message"]}</div>' for a in activities[:8]
    )
    st.markdown(items, unsafe_allow_html=True)


def _render_system_status() -> None:
    client = get_api_client()
    healthy = _check_backend_health(client)
    dot_color = "#15803D" if healthy else "#B91C1C"
    label = "Backend online" if healthy else "Backend unreachable"
    st.markdown(
        f'<span class="system-status-dot" style="background:{dot_color};"></span>{label}',
        unsafe_allow_html=True,
    )
    st.caption(api_settings.base_url)


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("### 📄 Proposal Generator")
        if current_role():
            st.caption(f"Role: {current_role()}")

        nav_col1, nav_col2 = st.columns(2)
        with nav_col1:
            if st.button("🏠 Dashboard", use_container_width=True):
                st.session_state.workflow_stage = "dashboard"
                st.rerun()
        with nav_col2:
            if st.button("➕ New", use_container_width=True):
                st.session_state.workflow_stage = "upload"
                st.session_state.requirement_document = None
                st.session_state.proposal_id = None
                st.session_state.proposal = None
                st.rerun()

        st.markdown('<div class="sidebar-section-title">Current Workflow</div>', unsafe_allow_html=True)
        _render_step_track(st.session_state.get("workflow_stage", "upload"))

        st.markdown('<div class="sidebar-section-title">Project Information</div>', unsafe_allow_html=True)
        _render_project_info()

        st.markdown('<div class="sidebar-section-title">Proposal Progress</div>', unsafe_allow_html=True)
        _render_progress()

        st.markdown('<div class="sidebar-section-title">Recent Activities</div>', unsafe_allow_html=True)
        _render_activities()

        st.markdown('<div class="sidebar-section-title">System Status</div>', unsafe_allow_html=True)
        _render_system_status()

        st.divider()
        if st.button("Sign out", use_container_width=True):
            logout()
            st.rerun()
