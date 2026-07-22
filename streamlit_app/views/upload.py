"""Step 1 — Upload Requirements.

Note: the backend's POST /proposals/requirement-documents accepts exactly
one file per proposal (Proposal.requirement_document_id is a 1:1 FK) and
runs OCR/extraction/capability-classification/knowledge-matching
synchronously in that same call. So the multi-file uploader below is for
convenience/validation UX — only the first valid file is actually sent,
and that one call already covers every 'hidden' Step 2 sub-stage except
proposal generation itself, which is the SSE stream Step 2 proper drives.
"""

import streamlit as st

from services.api_client import APIError
from services.auth import access_token, call_with_refresh, get_api_client
from utils.activity import log_activity

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "md", "txt", "png", "jpg", "jpeg"}
MAX_FILE_SIZE_MB = 25


def _validate_file(file) -> list[str]:
    errors = []
    extension = file.name.rsplit(".", 1)[-1].lower() if "." in file.name else ""
    if extension not in ALLOWED_EXTENSIONS:
        errors.append(f"unsupported file type (.{extension})")
    size_mb = file.size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        errors.append(f"{size_mb:.1f} MB exceeds the {MAX_FILE_SIZE_MB} MB limit")
    return errors


def _render_file_list(uploaded_files) -> "tuple[object, bool]":
    st.markdown("**Uploaded files**")
    has_errors = False
    for f in uploaded_files:
        errors = _validate_file(f)
        icon = "❌" if errors else "✅"
        st.markdown(f"{icon} **{f.name}** &nbsp;·&nbsp; {f.size / 1024:.1f} KB", unsafe_allow_html=True)
        for e in errors:
            has_errors = True
            st.caption(f"⚠️ {f.name}: {e}")

    if len(uploaded_files) > 1:
        st.warning(
            "Only one requirement document can be processed per proposal today — "
            f"**{uploaded_files[0].name}** will be used as the primary document. "
            "Remove the others to avoid confusion."
        )

    primary = uploaded_files[0] if uploaded_files and not has_errors else None
    return primary, has_errors


def render_upload_page() -> None:
    st.title("📤 Upload Requirements")
    st.caption("Step 1 of 4 — upload the RFP/requirement document and describe the proposal.")

    col_left, col_right = st.columns([1.3, 1])

    with col_left:
        st.markdown('<div class="app-card-title">📎 Requirement Documents</div>', unsafe_allow_html=True)
        uploaded_files = st.file_uploader(
            "Upload one or more RFP/requirement documents",
            type=sorted(ALLOWED_EXTENSIONS),
            accept_multiple_files=True,
        )

        primary_file = None
        if uploaded_files:
            primary_file, _ = _render_file_list(uploaded_files)
        else:
            st.markdown('<div class="app-card-subtle">No files uploaded yet.</div>', unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="app-card-title">🗂️ Proposal Details</div>', unsafe_allow_html=True)
        proposal_name = st.text_input("Proposal Name*")
        client_name = st.text_input("Client Name*")
        proposal_description = st.text_area(
            "Proposal Description",
            help="Optional context passed to the LLM alongside the extracted requirements.",
            height=140,
        )

    st.divider()

    validation_messages = []
    if not primary_file:
        validation_messages.append("Upload a valid requirement document to continue.")
    if not proposal_name.strip():
        validation_messages.append("Proposal Name is required.")
    if not client_name.strip():
        validation_messages.append("Client Name is required.")

    for msg in validation_messages:
        st.warning(msg)

    if st.button("Continue →", type="primary", disabled=bool(validation_messages)):
        with st.spinner("Uploading and analyzing the document — extraction, classification, and knowledge-base matching run now..."):
            try:
                client = get_api_client()
                response = call_with_refresh(
                    client.upload_requirement_document,
                    access_token=access_token(),
                    file_bytes=primary_file.getvalue(),
                    file_name=primary_file.name,
                    proposal_name=proposal_name.strip(),
                    client_name=client_name.strip(),
                    additional_context=proposal_description.strip() or None,
                )
            except APIError as exc:
                st.error(exc.detail)
                return

        st.session_state.requirement_document = response
        st.session_state.proposal_id = response["proposal_id"]
        st.session_state.workflow_stage = "processing"
        log_activity(f"Uploaded '{primary_file.name}' for {proposal_name.strip()}", icon="📤")
        st.rerun()
