"""Plain helpers shared by the test modules.

Kept out of conftest.py and imported as ``from helpers import ...`` (pytest puts
``test/`` on sys.path): ``from test.conftest import ...`` would not work here
because the repo has a top-level ``test.py`` script that shadows the ``test``
package name.
"""

from datetime import datetime, timedelta, timezone

from authentication.jwt_handler import create_access_token
from database.models import User

TEST_PASSWORD = "Admin@123"


def auth_headers(user: User) -> dict[str, str]:
    """A genuine token from the app's own jwt_handler — the auth dependency is
    never overridden, so every authenticated test exercises the real path."""

    token = create_access_token(user_id=user.id, email=user.email, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


def utc_now() -> datetime:
    """Naive UTC: the datetime columns are timezone-less and the OTP check
    compares against ``datetime.now(utc).replace(tzinfo=None)``."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def minutes_from_now(minutes: int) -> datetime:
    return utc_now() + timedelta(minutes=minutes)


def upload(name: str = "rfp.pdf", content: bytes = b"%PDF-1.4 fake pdf", content_type: str = "application/pdf"):
    """A multipart file tuple for httpx."""

    return (name, content, content_type)
