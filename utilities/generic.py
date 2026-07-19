import secrets
import string
import re
from pathlib import Path

from database.db_enum import UserRole


def assign_role(is_organization_admin: bool) -> UserRole:
    """Centralised role assignment: organisations become admins, individuals become users."""
    return UserRole.ADMIN if is_organization_admin else UserRole.USER


def generate_temp_password(length: int = 12) -> str:
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(length))



def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename for safe storage in S3.
    """
    if not filename or not filename.strip():
        return "untitled"

    path = Path(filename.strip())
    extension = path.suffix.lower()
    name = path.stem.strip().lower()

    if not name:
        return f"file{extension}"
    name = re.sub(r'[^a-z0-9_-]', '_', name)
    
    # Normalize multiple underscores and trim
    name = re.sub(r'_+', '_', name).strip('_')
    
    # Fallback if everything was stripped
    if not name:
        name = "file"

    return f"{name}{extension}"