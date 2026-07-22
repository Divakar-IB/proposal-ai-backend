import streamlit as st

DEFAULTS = {
    "auth_token": None,
    "refresh_token": None,
    "user_role": None,
    "workflow_stage": "upload",
    "requirement_document": None,
    "proposal_id": None,
    "proposal": None,
    "generation_events": [],
    "generation_running_for": None,
    "generation_done_for": None,
    "activity_log": [],
}


def init_session_state() -> None:
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value
