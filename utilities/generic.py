import secrets
import string
import re
from pathlib import Path

from database.db_enum import UserRole


def assign_role(is_organization_admin: bool) -> UserRole:
    """Centralised role assignment: organisations become admins, individuals become users."""
    return UserRole.ADMIN if is_organization_admin else UserRole.USER


# The frontend login form rejects anything shorter, so a temporary password
# below this is unusable no matter how it was produced.
MIN_TEMP_PASSWORD_LENGTH = 8

# Deliberately NOT string.punctuation. A temporary password has to survive a
# trip through an email and a copy-paste, which rules out:
#   < > &     mail clients that render the text part as HTML eat everything
#             between a '<' and the next '>' — a 12-char password can arrive
#             as 4 characters, or vanish entirely
#   " ' `     escaped, or auto-substituted with smart quotes
#   \         swallowed as an escape by some clients and terminals
# Ambiguous glyphs (0/O, 1/l/I) are dropped too — invitees retype these.
_TEMP_PASSWORD_SYMBOLS = "!#$%*+-=?@_"
_TEMP_PASSWORD_LOWER = "abcdefghijkmnopqrstuvwxyz"
_TEMP_PASSWORD_UPPER = "ABCDEFGHJKLMNPQRSTUVWXYZ"
_TEMP_PASSWORD_DIGITS = "23456789"


def generate_temp_password(length: int = 12) -> str:
    """Generate a cryptographically secure temporary password that survives
    being emailed: email-safe characters only, no ambiguous glyphs, and at
    least one lower/upper/digit/symbol so it also clears the strength rules
    the invitee will hit on first login."""

    if length < MIN_TEMP_PASSWORD_LENGTH:
        raise ValueError(f"temporary password length must be at least {MIN_TEMP_PASSWORD_LENGTH}, got {length}")

    classes = (
        _TEMP_PASSWORD_LOWER,
        _TEMP_PASSWORD_UPPER,
        _TEMP_PASSWORD_DIGITS,
        _TEMP_PASSWORD_SYMBOLS,
    )
    alphabet = "".join(classes)

    # One guaranteed character per class, remainder free, then shuffled so the
    # classes don't always land in the same positions.
    characters = [secrets.choice(group) for group in classes]
    characters += [secrets.choice(alphabet) for _ in range(length - len(classes))]
    secrets.SystemRandom().shuffle(characters)
    return "".join(characters)


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