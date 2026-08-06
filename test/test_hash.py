"""Password hashing and JWT primitives.

Was previously a print-based script importing a non-existent
`authentication.hash` module, so it errored during collection.
"""

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from authentication.dependency import hash_password, verify_password
from authentication.jwt_handler import (
    ALGORITHM,
    ISSUER,
    SECRET_KEY,
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    verify_access_token,
    verify_password_reset_token,
)

# ------------------------------------------------------------------
# Hashing
# ------------------------------------------------------------------


def test_hash_password_does_not_store_the_plaintext():
    hashed = hash_password("Admin@123")

    assert hashed != "Admin@123"
    assert hashed.startswith("$2")  # bcrypt


def test_verify_password_accepts_the_right_password():
    assert verify_password("Admin@123", hash_password("Admin@123")) is True


def test_verify_password_rejects_the_wrong_password():
    assert verify_password("WrongPassword", hash_password("Admin@123")) is False


def test_hashing_is_salted():
    """Two hashes of the same password must differ, and both must verify."""

    first = hash_password("Admin@123")
    second = hash_password("Admin@123")

    assert first != second
    assert verify_password("Admin@123", first)
    assert verify_password("Admin@123", second)


@pytest.mark.parametrize("password", ["", " ", "a", "ünïcodé-påss", "x" * 60])
def test_hashing_handles_edge_case_passwords(password):
    hashed = hash_password(password)

    assert verify_password(password, hashed) is True
    assert verify_password(password + "extra", hashed) is False


def test_bcrypt_only_considers_the_first_72_bytes():
    """A bcrypt property, not a bug in this codebase, but worth pinning: anything
    past 72 bytes is ignored, so two long passwords sharing a 72-byte prefix are
    interchangeable. Only matters if a maximum length is ever advertised.
    """

    hashed = hash_password("x" * 72)

    assert verify_password("x" * 72 + "ignored-tail", hashed) is True
    assert verify_password("x" * 71 + "y", hashed) is False


def test_verify_password_is_case_sensitive():
    hashed = hash_password("Admin@123")
    assert verify_password("admin@123", hashed) is False


# ------------------------------------------------------------------
# JWT
# ------------------------------------------------------------------


def test_access_token_round_trips():
    token = create_access_token(user_id=7, email="a@example.com", role="org_admin")

    payload = verify_access_token(token)

    assert payload["user_id"] == 7
    assert payload["email"] == "a@example.com"
    assert payload["role"] == "org_admin"
    assert payload["token_type"] == "access"
    assert payload["iss"] == ISSUER


def test_verify_access_token_rejects_a_refresh_token():
    assert verify_access_token(create_refresh_token(user_id=7)) is None


def test_verify_access_token_rejects_a_reset_token():
    token = create_password_reset_token(user_id=7, expire_minutes=10)
    assert verify_access_token(token) is None


def test_verify_access_token_rejects_garbage():
    assert verify_access_token("not-a-jwt") is None


def test_verify_access_token_rejects_a_foreign_signature():
    forged = jwt.encode({"user_id": 1, "token_type": "access"}, "other-secret", algorithm=ALGORITHM)
    assert verify_access_token(forged) is None


def test_verify_access_token_rejects_a_wrong_issuer():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "user_id": 1,
            "token_type": "access",
            "iss": "somebody-else",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    assert verify_access_token(token) is None


def test_verify_access_token_rejects_an_expired_token():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "user_id": 1,
            "token_type": "access",
            "iss": ISSUER,
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    assert verify_access_token(token) is None


def test_password_reset_token_round_trips():
    token = create_password_reset_token(user_id=42, expire_minutes=10)

    payload = verify_password_reset_token(token)

    assert payload["user_id"] == 42
    assert payload["token_type"] == "password_reset"


def test_verify_password_reset_token_rejects_an_access_token():
    token = create_access_token(user_id=1, email="a@example.com", role="member")
    assert verify_password_reset_token(token) is None


def test_password_reset_token_can_be_created_already_expired():
    """`expire_minutes` is caller-supplied; a non-positive value must not yield a
    usable token."""

    token = create_password_reset_token(user_id=1, expire_minutes=-1)
    assert verify_password_reset_token(token) is None
