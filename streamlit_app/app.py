import streamlit as st

from components.login import render_login_gate
from components.sidebar import render_sidebar
from config.settings import app_settings
from utils.session import init_session_state
from utils.styling import inject_theme
from views.dashboard import render_dashboard_page
from views.export import render_export_page
from views.processing import render_processing_page
from views.review import render_review_page
from views.upload import render_upload_page

st.set_page_config(
    page_title=app_settings.title,
    page_icon=app_settings.page_icon,
    layout=app_settings.layout,
    initial_sidebar_state="expanded",
)

init_session_state()
inject_theme()

if not render_login_gate():
    st.stop()

render_sidebar()

stage = st.session_state.workflow_stage

if stage == "upload":
    render_upload_page()
elif stage == "processing":
    render_processing_page()
elif stage == "review":
    render_review_page()
elif stage == "export":
    render_export_page()
elif stage == "dashboard":
    render_dashboard_page()
else:
    st.session_state.workflow_stage = "upload"
    st.rerun()
