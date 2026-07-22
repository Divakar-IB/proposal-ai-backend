"""Step 2 — Backend Processing (hidden as a distinct page; this view is
reached automatically from Upload, never linked to directly).

OCR/extraction/capability-classification/knowledge-matching already ran
synchronously inside Step 1's upload call. What happens here is the
proposal-generation SSE stream (POST /proposals/generate) — the
per-section draft -> quality-check -> revise loop.
"""

import streamlit as st

from services.api_client import APIError
from services.auth import access_token, get_api_client, try_refresh_access_token
from utils.activity import log_activity
from utils.formatting import confidence_label, section_status_badge

TOTAL_SECTIONS = 14  # mirrors generation/sections.py::SECTION_DEFINITIONS


def _reset_to_upload() -> None:
    st.session_state.workflow_stage = "upload"
    st.session_state.requirement_document = None
    st.session_state.proposal_id = None
    st.session_state.proposal = None


def _fetch_and_transition_to_review(client, proposal_id: int) -> None:
    try:
        proposal = client.get_proposal(proposal_id)
    except APIError as exc:
        st.error(f"Generation finished but the proposal could not be loaded: {exc.detail}")
        return
    st.session_state.proposal = proposal
    st.session_state.workflow_stage = "review"
    log_activity("Proposal generation completed", icon="✅")
    st.rerun()


def _render_sections(placeholder, sections: dict) -> None:
    if not sections:
        placeholder.markdown(
            '<div class="app-card-subtle">Waiting for the first section to start drafting...</div>',
            unsafe_allow_html=True,
        )
        return
    rows = []
    for section in sections.values():
        badge = section_status_badge(section.get("status"))
        confidence = confidence_label(section.get("confidence_score"))
        flag = " 🚩" if section.get("review_flag") else ""
        rows.append(
            '<div class="app-card" style="margin-bottom:0.5rem;padding:0.6rem 0.9rem;">'
            f'<b>{section.get("title", section.get("key"))}</b>{flag} &nbsp; {badge} &nbsp; '
            f'<span class="app-card-subtle">confidence: {confidence}</span></div>'
        )
    placeholder.markdown("".join(rows), unsafe_allow_html=True)


def render_processing_page() -> None:
    st.title("⚙️ Generating Your Proposal")
    st.caption("Step 2 of 4 — this runs automatically. Sit tight while each section drafts and self-checks.")

    requirement_document = st.session_state.get("requirement_document")
    proposal_id = st.session_state.get("proposal_id")
    if not requirement_document or not proposal_id:
        st.warning("No proposal in progress — start again from Upload Requirements.")
        if st.button("← Back to Upload"):
            _reset_to_upload()
            st.rerun()
        return

    client = get_api_client()

    if st.session_state.get("generation_done_for") == proposal_id:
        _fetch_and_transition_to_review(client, proposal_id)
        return

    if st.session_state.get("generation_running_for") == proposal_id:
        st.info("Generation is already running for this proposal in another run — please wait.")
        return

    st.session_state.generation_running_for = proposal_id

    progress_bar = st.progress(0.0)
    stage_placeholder = st.empty()
    sections_placeholder = st.empty()

    sections: dict[str, dict] = {}
    _render_sections(sections_placeholder, sections)

    try:
        for event in client.generate_proposal(
            access_token=access_token(),
            requirement_document_id=requirement_document["id"],
        ):
            if event.event == "section":
                data = event.data
                sections[data["key"]] = data
                progress_bar.progress(min(len(sections) / TOTAL_SECTIONS, 1.0))
                stage_placeholder.markdown(
                    f"**Latest:** {data.get('title', data['key'])} → *{data.get('status')}*"
                )
                _render_sections(sections_placeholder, sections)
            elif event.event == "error":
                st.warning(event.data.get("message", "A recoverable error occurred mid-generation."))
            elif event.event == "failed":
                st.session_state.generation_running_for = None
                st.error(event.data.get("message", "Proposal generation failed."))
                if st.button("Retry generation"):
                    st.rerun()
                return
            elif event.event == "done":
                st.session_state.generation_running_for = None
                st.session_state.generation_done_for = proposal_id
                progress_bar.progress(1.0)
                _fetch_and_transition_to_review(client, proposal_id)
                return
    except APIError as exc:
        st.session_state.generation_running_for = None
        if exc.status_code == 401:
            try_refresh_access_token()
        st.error(exc.detail)
        if st.button("Retry generation"):
            st.rerun()
