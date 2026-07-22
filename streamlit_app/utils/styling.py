from pathlib import Path

import streamlit as st

_THEME_CSS_PATH = Path(__file__).resolve().parent.parent / "styles" / "theme.css"


def inject_theme() -> None:
    css = _THEME_CSS_PATH.read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
