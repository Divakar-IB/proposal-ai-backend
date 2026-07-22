"""Central configuration for the Streamlit frontend.

Mirrors the backend's config.py pattern (single source of truth, no
scattered os.getenv calls) but reads plain environment variables / a local
.env since this app is deployed separately from the FastAPI backend.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class APISettings:
    base_url: str = os.getenv("API_BASE_URL", "http://localhost:8000")
    timeout_seconds: float = float(os.getenv("API_TIMEOUT_SECONDS", "30"))
    stream_timeout_seconds: float = float(os.getenv("API_STREAM_TIMEOUT_SECONDS", "600"))


@dataclass(frozen=True)
class AppSettings:
    title: str = "Proposal Generator"
    page_icon: str = "📄"
    layout: str = "wide"


api_settings = APISettings()
app_settings = AppSettings()
