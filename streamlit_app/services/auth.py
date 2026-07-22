"""Session-state-aware auth helpers. Pure API concerns live in api_client.py;
this module is the only place that touches st.session_state for tokens."""

from typing import Optional

import streamlit as st

from services.api_client import APIError, ProposalAPIClient


@st.cache_resource(show_spinner=False)
def get_api_client() -> ProposalAPIClient:
    return ProposalAPIClient()


def is_authenticated() -> bool:
    return bool(st.session_state.get("auth_token"))


def current_role() -> Optional[str]:
    return st.session_state.get("user_role")


def access_token() -> Optional[str]:
    return st.session_state.get("auth_token")


def login(email: str, password: str) -> tuple[bool, Optional[str]]:
    """Attempts login, storing tokens in session state on success.
    Returns (success, error_message)."""
    client = get_api_client()
    try:
        result = client.login(email, password)
    except APIError as exc:
        return False, exc.detail

    st.session_state.auth_token = result["access_token"]
    st.session_state.refresh_token = result["refresh_token"]
    st.session_state.user_role = result["role"]
    return True, None


def logout() -> None:
    for key in ("auth_token", "refresh_token", "user_role"):
        st.session_state[key] = None
    # A fresh login should start the workflow clean, not resume mid-way
    # through whatever the previous session was doing.
    st.session_state.workflow_stage = "upload"
    st.session_state.requirement_document = None
    st.session_state.proposal_id = None
    st.session_state.proposal = None


def try_refresh_access_token() -> bool:
    """Called after a 401 on a mutating call — refreshes the access token
    using the stored refresh token instead of forcing a full re-login."""
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        return False
    client = get_api_client()
    try:
        result = client.refresh_access_token(refresh_token)
    except APIError:
        return False
    st.session_state.auth_token = result["access_token"]
    return True


def call_with_refresh(fn, *args, **kwargs):
    """Runs an authenticated api_client call, retrying once after a token
    refresh if the first attempt hits a 401 (access token expired)."""
    try:
        return fn(*args, **kwargs)
    except APIError as exc:
        if exc.status_code == 401 and try_refresh_access_token():
            kwargs["access_token"] = access_token()
            return fn(*args, **kwargs)
        raise
