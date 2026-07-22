"""Session-scoped activity log for the sidebar's 'Recent Activities' panel.
Purely in-memory — it's a UX trail for the current session, not an audit log."""

import streamlit as st

MAX_ACTIVITIES = 20


def log_activity(message: str, icon: str = "•") -> None:
    activities = st.session_state.setdefault("activity_log", [])
    activities.insert(0, {"message": message, "icon": icon})
    del activities[MAX_ACTIVITIES:]


def get_activities() -> list[dict]:
    return st.session_state.get("activity_log", [])
