"""/auth — register, login, the forgot-password OTP flow, password changes and
admin user creation."""

import pytest
from helpers import TEST_PASSWORD, auth_headers, minutes_from_now

from authentication.jwt_handler import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
)
from database.crud import get_user_by_email
from database.db_enum import UserRole


# ------------------------------------------------------------------
# POST /auth/register
# ------------------------------------------------------------------

async def test_register_creates_user(client, db):
    response = await client.post(
        "/auth/register",
        json={"email": "new@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Registered successfully", "email": "new@example.com"}
    assert await get_user_by_email(db, "new@example.com") is not None


async def test_register_hashes_the_password(client, db):
    await client.post(
        "/auth/register",
        json={"email": "hashed@example.com", "password": "Secret@123", "role": "member"},
    )

    user = await get_user_by_email(db, "hashed@example.com")
    assert user.hashed_password != "Secret@123"
    assert user.is_first_login is True


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: auth_service.register calls utilities.generic.assign_role(), which expects a "
        "bool but is handed a UserRole. Every non-empty enum value is truthy, so self-"
        "registration always produces an org_admin regardless of the requested role."
    ),
)
async def test_register_honours_the_requested_role(client, db):
    await client.post(
        "/auth/register",
        json={"email": "plain@example.com", "password": "Secret@123", "role": "member"},
    )

    user = await get_user_by_email(db, "plain@example.com")
    assert user.role == UserRole.USER


async def test_register_rejects_duplicate_email(client, factory):
    await factory.user(email="taken@example.com")

    response = await client.post(
        "/auth/register",
        json={"email": "taken@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


async def test_register_rejects_duplicate_email_of_a_soft_deleted_user(client, factory):
    """get_user_by_email deliberately ignores is_active — a removed member's
    address stays reserved, so re-registering it must still 409."""

    await factory.user(email="gone@example.com", is_active=False)

    response = await client.post(
        "/auth/register",
        json={"email": "gone@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "Secret@123", "role": "member"},
        {"email": "a@example.com", "password": "Secret@123", "role": "superuser"},
        {"email": "a@example.com", "password": "Secret@123"},
        {"email": "a@example.com", "role": "member"},
        {},
    ],
    ids=["bad-email", "unknown-role", "no-role", "no-password", "empty-body"],
)
async def test_register_validation_errors(client, payload):
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 422


# ------------------------------------------------------------------
# POST /auth/login
# ------------------------------------------------------------------

async def test_login_returns_tokens_and_role(client, factory):
    user = await factory.user(email="login@example.com", role=UserRole.ADMIN)

    response = await client.post(
        "/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "org_admin"
    assert body["access_token"] and body["refresh_token"]


async def test_login_token_is_accepted_by_a_protected_route(client, factory):
    user = await factory.user(email="usable@example.com")

    login = await client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    token = login.json()["access_token"]

    profile = await client.get("/profile", headers={"Authorization": f"Bearer {token}"})
    assert profile.status_code == 200
    assert profile.json()["email"] == "usable@example.com"


async def test_login_rejects_wrong_password(client, factory):
    user = await factory.user(email="wrong@example.com")

    response = await client.post("/auth/login", json={"email": user.email, "password": "Nope@1234"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_login_rejects_unknown_email_with_the_same_message(client):
    """Unknown address and wrong password must be indistinguishable."""

    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


async def test_login_rejects_inactive_account(client, factory):
    user = await factory.user(email="inactive@example.com", is_active=False)

    response = await client.post(
        "/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )

    assert response.status_code == 403
    assert "inactive" in response.json()["detail"].lower()


async def test_login_validates_email_format(client):
    response = await client.post("/auth/login", json={"email": "nope", "password": "x"})
    assert response.status_code == 422


# ------------------------------------------------------------------
# POST /auth/forgot_password
# ------------------------------------------------------------------

GENERIC_MESSAGE = "If this email is registered, an OTP has been sent to it."


async def test_forgot_password_sends_otp_to_a_registered_user(client, factory, db, sent_emails):
    user = await factory.user(email="forgot@example.com")

    response = await client.post("/auth/forgot_password", json={"email": user.email})

    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_MESSAGE
    await db.refresh(user)
    assert user.otp_code is not None
    assert user.otp_expires_at is not None
    assert [email.kind for email in sent_emails] == ["otp"]


async def test_forgot_password_does_not_leak_unknown_emails(client, sent_emails):
    response = await client.post("/auth/forgot_password", json={"email": "ghost@example.com"})

    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_MESSAGE
    assert sent_emails == []


async def test_forgot_password_ignores_inactive_users(client, factory, db, sent_emails):
    user = await factory.user(email="dead@example.com", is_active=False)

    response = await client.post("/auth/forgot_password", json={"email": user.email})

    assert response.status_code == 200
    await db.refresh(user)
    assert user.otp_code is None
    assert sent_emails == []


async def test_forgot_password_survives_a_mail_outage(client, factory, db, monkeypatch):
    """A broken SMTP provider must not turn into a 500 — that would also make a
    registered address distinguishable from an unknown one."""

    import authentication.auth_service as auth_service

    async def explode(*args, **kwargs):
        raise RuntimeError("smtp is down")

    monkeypatch.setattr(auth_service, "send_otp_email", explode)
    user = await factory.user(email="outage@example.com")

    response = await client.post("/auth/forgot_password", json={"email": user.email})

    assert response.status_code == 200
    assert response.json()["message"] == GENERIC_MESSAGE
    await db.refresh(user)
    assert user.otp_code is not None  # stored anyway, so a resend still works


async def test_forgot_password_validates_email(client):
    response = await client.post("/auth/forgot_password", json={"email": "bad"})
    assert response.status_code == 422


# ------------------------------------------------------------------
# POST /auth/verify_otp
# ------------------------------------------------------------------

async def test_verify_otp_returns_a_reset_token_and_consumes_the_otp(client, factory, db):
    user = await factory.user(
        email="otp@example.com", otp_code="123456", otp_expires_at=minutes_from_now(10)
    )

    response = await client.post(
        "/auth/verify_otp", json={"email": user.email, "otp": "123456"}
    )

    assert response.status_code == 200
    assert response.json()["reset_token"]
    await db.refresh(user)
    assert user.otp_code is None
    assert user.otp_expires_at is None


async def test_verify_otp_is_single_use(client, factory):
    user = await factory.user(
        email="once@example.com", otp_code="123456", otp_expires_at=minutes_from_now(10)
    )

    first = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})
    second = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})

    assert first.status_code == 200
    assert second.status_code == 400


async def test_verify_otp_rejects_expired_otp(client, factory):
    user = await factory.user(
        email="expired@example.com", otp_code="123456", otp_expires_at=minutes_from_now(-1)
    )

    response = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid or expired OTP"


async def test_verify_otp_rejects_wrong_code(client, factory):
    user = await factory.user(
        email="mismatch@example.com", otp_code="123456", otp_expires_at=minutes_from_now(10)
    )

    response = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "000000"})

    assert response.status_code == 400


async def test_verify_otp_rejects_user_without_a_pending_otp(client, factory):
    user = await factory.user(email="nootp@example.com")

    response = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})

    assert response.status_code == 400


async def test_verify_otp_rejects_unknown_email(client):
    response = await client.post(
        "/auth/verify_otp", json={"email": "ghost@example.com", "otp": "123456"}
    )
    assert response.status_code == 400


async def test_verify_otp_rejects_inactive_user(client, factory):
    user = await factory.user(
        email="off@example.com",
        is_active=False,
        otp_code="123456",
        otp_expires_at=minutes_from_now(10),
    )

    response = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})

    assert response.status_code == 400


# ------------------------------------------------------------------
# POST /auth/new_password
# ------------------------------------------------------------------

async def test_new_password_completes_the_forgot_password_flow(client, factory):
    user = await factory.user(
        email="flow@example.com", otp_code="123456", otp_expires_at=minutes_from_now(10)
    )

    verified = await client.post("/auth/verify_otp", json={"email": user.email, "otp": "123456"})
    reset_token = verified.json()["reset_token"]

    changed = await client.post(
        "/auth/new_password", json={"reset_token": reset_token, "new_password": "Brand@New1"}
    )
    assert changed.status_code == 200

    old = await client.post("/auth/login", json={"email": user.email, "password": TEST_PASSWORD})
    new = await client.post("/auth/login", json={"email": user.email, "password": "Brand@New1"})
    assert old.status_code == 401
    assert new.status_code == 200


async def test_new_password_rejects_a_garbage_token(client):
    response = await client.post(
        "/auth/new_password", json={"reset_token": "not-a-jwt", "new_password": "Brand@New1"}
    )
    assert response.status_code == 401


async def test_new_password_rejects_an_access_token(client, factory):
    """Token type is checked, so a login token cannot be swapped in for a
    password-reset token."""

    user = await factory.user(email="swap@example.com")
    access_token = create_access_token(user.id, user.email, user.role.value)

    response = await client.post(
        "/auth/new_password", json={"reset_token": access_token, "new_password": "Brand@New1"}
    )

    assert response.status_code == 401


async def test_new_password_rejects_a_refresh_token(client, factory):
    user = await factory.user(email="refresh@example.com")
    refresh_token = create_refresh_token(user.id)

    response = await client.post(
        "/auth/new_password", json={"reset_token": refresh_token, "new_password": "Brand@New1"}
    )

    assert response.status_code == 401


async def test_new_password_rejects_an_expired_token(client, factory):
    user = await factory.user(email="stale@example.com")
    expired = create_password_reset_token(user.id, expire_minutes=-1)

    response = await client.post(
        "/auth/new_password", json={"reset_token": expired, "new_password": "Brand@New1"}
    )

    assert response.status_code == 401


async def test_new_password_404s_when_the_user_was_removed_meanwhile(client, factory, db):
    user = await factory.user(email="removed@example.com")
    token = create_password_reset_token(user.id, expire_minutes=10)

    user.is_active = False
    await db.commit()

    response = await client.post(
        "/auth/new_password", json={"reset_token": token, "new_password": "Brand@New1"}
    )

    assert response.status_code == 404


async def test_new_password_enforces_minimum_length(client, factory):
    user = await factory.user(email="short@example.com")
    token = create_password_reset_token(user.id, expire_minutes=10)

    response = await client.post(
        "/auth/new_password", json={"reset_token": token, "new_password": "Short1"}
    )

    assert response.status_code == 422


# ------------------------------------------------------------------
# POST /auth/reset_password (authenticated)
# ------------------------------------------------------------------

async def test_reset_password_changes_the_password(client, factory):
    user = await factory.user(email="change@example.com")

    response = await client.post(
        "/auth/reset_password",
        headers=auth_headers(user),
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "Another@1",
            "confirm_password": "Another@1",
        },
    )

    assert response.status_code == 200
    login = await client.post("/auth/login", json={"email": user.email, "password": "Another@1"})
    assert login.status_code == 200


async def test_reset_password_rejects_wrong_current_password(client, factory):
    user = await factory.user(email="badcurrent@example.com")

    response = await client.post(
        "/auth/reset_password",
        headers=auth_headers(user),
        json={
            "current_password": "Totally@Wrong1",
            "new_password": "Another@1",
            "confirm_password": "Another@1",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Current password is incorrect"


async def test_reset_password_rejects_mismatched_confirmation(client, factory):
    user = await factory.user(email="mismatch2@example.com")

    response = await client.post(
        "/auth/reset_password",
        headers=auth_headers(user),
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "Another@1",
            "confirm_password": "Different@1",
        },
    )

    assert response.status_code == 422


async def test_reset_password_rejects_short_new_password(client, factory):
    user = await factory.user(email="tiny@example.com")

    response = await client.post(
        "/auth/reset_password",
        headers=auth_headers(user),
        json={"current_password": TEST_PASSWORD, "new_password": "Ab1!", "confirm_password": "Ab1!"},
    )

    assert response.status_code == 422


async def test_reset_password_404s_for_a_deleted_user(client, factory, db):
    user = await factory.user(email="vanished@example.com")
    headers = auth_headers(user)

    user.is_active = False
    await db.commit()

    response = await client.post(
        "/auth/reset_password",
        headers=headers,
        json={
            "current_password": TEST_PASSWORD,
            "new_password": "Another@1",
            "confirm_password": "Another@1",
        },
    )

    assert response.status_code == 404


# ------------------------------------------------------------------
# POST /auth/create-user (admin only)
# ------------------------------------------------------------------

async def test_admin_can_create_a_user(client, admin_headers, db):
    response = await client.post(
        "/auth/create-user",
        headers=admin_headers,
        json={"email": "created@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "created@example.com"
    created = await get_user_by_email(db, "created@example.com")
    assert created.role == UserRole.USER  # unlike /register, the role is used verbatim


async def test_create_user_rejects_duplicate_email(client, admin_headers, factory):
    await factory.user(email="dupe@example.com")

    response = await client.post(
        "/auth/create-user",
        headers=admin_headers,
        json={"email": "dupe@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 409


async def test_create_user_is_forbidden_for_members(client, member_headers):
    response = await client.post(
        "/auth/create-user",
        headers=member_headers,
        json={"email": "nope@example.com", "password": "Secret@123", "role": "member"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have permission to perform this action."


# ------------------------------------------------------------------
# Token handling on protected routes
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "headers, expected",
    [
        ({}, 401),
        ({"Authorization": "Bearer "}, 401),
        ({"Authorization": "Token abc"}, 401),
        ({"Authorization": "Bearer not-a-jwt"}, 401),
    ],
    ids=["missing", "empty-credentials", "wrong-scheme", "malformed-jwt"],
)
async def test_protected_route_rejects_bad_authorization_headers(client, headers, expected):
    response = await client.get("/profile", headers=headers)
    assert response.status_code == expected


async def test_protected_route_rejects_a_token_signed_with_another_key(client, factory):
    from jose import jwt

    user = await factory.user()
    forged = jwt.encode(
        {"user_id": user.id, "email": user.email, "role": user.role.value, "token_type": "access"},
        "some-other-secret",
        algorithm="HS256",
    )

    response = await client.get("/profile", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 401


async def test_protected_route_rejects_a_refresh_token(client, factory):
    user = await factory.user()
    refresh_token = create_refresh_token(user.id)

    response = await client.get("/profile", headers={"Authorization": f"Bearer {refresh_token}"})

    assert response.status_code == 401
