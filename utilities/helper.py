import secrets
import string

from database.db_enum import UserRole


def assign_role(is_organization_admin: bool) -> UserRole:
    """Centralised role assignment: organisations become admins, individuals become users."""
    return UserRole.ADMIN if is_organization_admin else UserRole.USER


def generate_temp_password(length: int = 12) -> str:
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(alphabet) for _ in range(length))
