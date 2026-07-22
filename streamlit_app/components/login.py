import streamlit as st

from services.auth import is_authenticated, login
from utils.activity import log_activity


def render_login_gate() -> bool:
    """Renders a centered login form. Returns True once authenticated —
    callers should st.stop() when this returns False so nothing below it
    on the page renders."""
    if is_authenticated():
        return True

    st.title("📄 Proposal Generator")
    st.caption("Sign in to continue")

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        with st.form("login_form", border=True):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", use_container_width=True)

        if submitted:
            if not email or not password:
                st.error("Enter both email and password.")
            else:
                with st.spinner("Signing in..."):
                    success, error = login(email, password)
                if success:
                    log_activity(f"Signed in as {email}", icon="🔑")
                    st.rerun()
                else:
                    st.error(error or "Login failed.")

    return False
