"""Dashboard — recent proposals, history, and quick actions.

Backed by GET /proposals (added alongside this frontend — the backend
previously only supported fetch-by-id)."""

import streamlit as st

from services.api_client import APIError
from services.auth import get_api_client
from utils.activity import log_activity
from utils.formatting import proposal_status_badge, time_ago

PAGE_SIZE = 10
STATUS_OPTIONS = ["All", "inprogress", "generating", "review", "done", "failed"]


def _open_proposal(client, proposal_id: int) -> None:
    try:
        proposal = client.get_proposal(proposal_id)
        requirement_document = client.get_requirement_document(proposal["requirement_document_id"])
    except APIError as exc:
        st.error(exc.detail)
        return

    st.session_state.proposal = proposal
    st.session_state.proposal_id = proposal_id
    st.session_state.requirement_document = requirement_document
    st.session_state.workflow_stage = "review"
    log_activity(f"Opened proposal '{proposal.get('title')}'", icon="📂")
    st.rerun()


def _start_new_proposal() -> None:
    st.session_state.workflow_stage = "upload"
    st.session_state.requirement_document = None
    st.session_state.proposal_id = None
    st.session_state.proposal = None


def render_dashboard_page() -> None:
    st.title("📊 Dashboard")
    st.caption("Recent proposal activity across your workspace.")

    client = get_api_client()

    col_new, col_search, col_status = st.columns([1, 2, 1])
    with col_new:
        st.markdown("&nbsp;")
        if st.button("➕ New Proposal", type="primary", use_container_width=True):
            _start_new_proposal()
            st.rerun()
    with col_search:
        search = st.text_input("Search by client name", key="dashboard_search")
    with col_status:
        status_filter = st.selectbox("Status", STATUS_OPTIONS, key="dashboard_status")

    try:
        result = client.list_proposals(
            client_name=search or None,
            status=None if status_filter == "All" else status_filter,
            page=1,
            limit=PAGE_SIZE,
        )
    except APIError as exc:
        st.error(exc.detail)
        return

    proposals = result.get("data", [])
    total = result.get("total", 0)
    completed = sum(1 for p in proposals if p["status"] == "done")
    pending_review = sum(1 for p in proposals if p["status"] == "review")

    st.markdown('<div class="app-card-title">📈 Overview</div>', unsafe_allow_html=True)
    tiles = [
        ("Total Proposals", total),
        ("Pending Review", pending_review),
        ("Completed", completed),
        ("Showing", len(proposals)),
    ]
    cols = st.columns(4)
    for col, (label, value) in zip(cols, tiles):
        with col:
            st.markdown(
                f'<div class="stat-tile"><div class="stat-value">{value}</div>'
                f'<div class="stat-label">{label}</div></div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader("Recent Proposals")

    if not proposals:
        st.markdown(
            '<div class="app-card-subtle">No proposals yet — start one from Upload Requirements.</div>',
            unsafe_allow_html=True,
        )
        return

    for proposal in proposals:
        cols = st.columns([3, 2, 2, 2, 1])
        with cols[0]:
            st.markdown(f"**{proposal['title']}**")
        with cols[1]:
            st.markdown(f"Client: {proposal['client_name']}")
        with cols[2]:
            st.markdown(proposal_status_badge(proposal["status"]), unsafe_allow_html=True)
        with cols[3]:
            st.markdown(
                f"{proposal['approved_sections']}/{proposal['total_sections']} approved "
                f"&nbsp;·&nbsp; {time_ago(proposal['created_at'])}",
                unsafe_allow_html=True,
            )
        with cols[4]:
            if st.button("Open →", key=f"open_{proposal['id']}"):
                _open_proposal(client, proposal["id"])

    if total > PAGE_SIZE:
        st.caption(f"Showing the {PAGE_SIZE} most recent of {total} proposals.")
