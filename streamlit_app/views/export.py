"""Step 4 — Export (UI only).

The backend has no export/download endpoints yet — Proposal.markdown_path
is written internally by the generation graph, but nothing serves it back,
and there's no docx/pdf/ppt rendering step or email-send endpoint. Per the
brief, this page is placeholder UI: real buttons, clearly disabled, wired
up the moment those endpoints exist.
"""

import streamlit as st

from utils.activity import log_activity
from utils.formatting import proposal_status_badge

EXPORT_OPTIONS = [
    ("📄", "Download DOCX"),
    ("📕", "Download PDF"),
    ("📊", "Download PPT"),
    ("✉️", "Send Email"),
]


def render_export_page() -> None:
    proposal = st.session_state.get("proposal")
    if not proposal:
        st.warning("No proposal loaded — start again from Upload Requirements.")
        if st.button("← Back to Upload"):
            st.session_state.workflow_stage = "upload"
            st.rerun()
        return

    st.title("📦 Export")
    st.caption("Step 4 of 4 — export the finished proposal.")

    st.markdown(
        f"""<div class="app-card">
        <b>{proposal.get('title')}</b> &nbsp; {proposal_status_badge(proposal.get('status'))}<br/>
        <span class="app-card-subtle">Client: {proposal.get('client_name', '—')}</span>
        </div>""",
        unsafe_allow_html=True,
    )

    st.info(
        "Export is not wired up to the backend yet — no docx/pdf/ppt rendering or email-send "
        "endpoint exists today. The buttons below are placeholders for that upcoming work."
    )

    cols = st.columns(len(EXPORT_OPTIONS))
    for col, (icon, label) in zip(cols, EXPORT_OPTIONS):
        with col:
            st.button(f"{icon} {label}", disabled=True, use_container_width=True)
            st.caption("Coming soon")

    st.divider()
    col_back, col_finish = st.columns(2)
    with col_back:
        if st.button("← Back to Review", use_container_width=True):
            st.session_state.workflow_stage = "review"
            st.rerun()
    with col_finish:
        if st.button("Finish → Dashboard", type="primary", use_container_width=True):
            log_activity(f"Finished proposal '{proposal.get('title')}'", icon="🏁")
            st.session_state.workflow_stage = "dashboard"
            st.rerun()
