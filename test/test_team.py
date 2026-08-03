"""/team — admin-only member management: invite, list, role changes,
activate/deactivate and soft delete."""

import pytest
from helpers import auth_headers

from database.db_enum import UserRole


# ------------------------------------------------------------------
# POST /team/invite
# ------------------------------------------------------------------

async def test_invite_creates_the_member_and_emails_a_temporary_password(
    client, admin_headers, db, sent_emails
):
    response = await client.post(
        "/team/invite", headers=admin_headers, json={"email": "invitee@example.com", "role": "member"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "message": "Invitation sent successfully.",
        "email": "invitee@example.com",
        "role": "member",
    }

    from database.crud import get_user_by_email

    invited = await get_user_by_email(db, "invitee@example.com")
    assert invited is not None
    assert invited.is_first_login is True
    assert [email.kind for email in sent_emails] == ["invite"]
    # The generated password is emailed, never returned in the response body.
    assert "password" not in response.text


async def test_invite_rejects_an_existing_email(client, admin_headers, factory):
    await factory.user(email="already@example.com")

    response = await client.post(
        "/team/invite", headers=admin_headers, json={"email": "already@example.com", "role": "member"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "A user with this email already exists"


async def test_invite_reports_502_when_the_email_fails_but_keeps_the_account(
    client, admin_headers, db, monkeypatch
):
    """The row is already committed when the mail fails, so a retry would hit
    the 409 above — the 502 is what tells the admin to resend instead."""

    import services.team_service as team_service

    async def explode(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(team_service, "send_team_invite_email", explode)

    response = await client.post(
        "/team/invite", headers=admin_headers, json={"email": "orphan@example.com", "role": "member"}
    )

    assert response.status_code == 502
    from database.crud import get_user_by_email

    assert await get_user_by_email(db, "orphan@example.com") is not None


async def test_invite_is_forbidden_for_members(client, member_headers):
    response = await client.post(
        "/team/invite", headers=member_headers, json={"email": "x@example.com", "role": "member"}
    )
    assert response.status_code == 403


async def test_invite_requires_a_token(client):
    response = await client.post("/team/invite", json={"email": "x@example.com", "role": "member"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    "payload",
    [{"email": "nope", "role": "member"}, {"email": "a@example.com", "role": "boss"}, {"role": "member"}],
    ids=["bad-email", "bad-role", "no-email"],
)
async def test_invite_validation_errors(client, admin_headers, payload):
    response = await client.post("/team/invite", headers=admin_headers, json=payload)
    assert response.status_code == 422


# ------------------------------------------------------------------
# GET /team/members
# ------------------------------------------------------------------

async def test_list_members_returns_newest_first_with_pagination_meta(client, admin, factory):
    await factory.user(email="one@example.com")
    await factory.user(email="two@example.com")

    response = await client.get("/team/members", headers=auth_headers(admin))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["page"] == 1
    assert body["limit"] == 10
    assert body["total_pages"] == 1
    assert len(body["data"]) == 3


async def test_list_members_never_exposes_credentials(client, admin_headers):
    response = await client.get("/team/members", headers=admin_headers)

    assert response.status_code == 200
    assert "hashed_password" not in response.text
    assert "otp_code" not in response.text


async def test_list_members_includes_deactivated_members(client, admin, factory):
    await factory.user(email="off@example.com", is_active=False)

    response = await client.get("/team/members", headers=auth_headers(admin))

    statuses = {row["email"]: row["status"] for row in response.json()["data"]}
    assert statuses["off@example.com"] == "inactive"
    assert statuses[admin.email] == "active"


async def test_list_members_paginates(client, admin, factory):
    for index in range(4):
        await factory.user(email=f"page{index}@example.com")

    first = await client.get("/team/members?page=1&limit=2", headers=auth_headers(admin))
    second = await client.get("/team/members?page=2&limit=2", headers=auth_headers(admin))

    assert first.json()["total"] == 5
    assert first.json()["total_pages"] == 3
    assert len(first.json()["data"]) == 2
    ids = {row["id"] for row in first.json()["data"]} | {row["id"] for row in second.json()["data"]}
    assert len(ids) == 4  # no overlap between pages


async def test_list_members_404s_when_the_page_is_past_the_end(client, admin_headers):
    """The endpoint treats an empty page as "no data available" rather than
    returning an empty list."""

    response = await client.get("/team/members?page=99", headers=admin_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "No data available"


async def test_list_members_is_forbidden_for_members(client, member_headers):
    response = await client.get("/team/members", headers=member_headers)
    assert response.status_code == 403


# ------------------------------------------------------------------
# PATCH /team/members/{id}/role
# ------------------------------------------------------------------

async def test_promote_a_member_to_admin(client, admin_headers, factory, db):
    member = await factory.user(email="promote@example.com", role=UserRole.USER)

    response = await client.patch(
        f"/team/members/{member.id}/role", headers=admin_headers, json={"role": "org_admin"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "org_admin"
    await db.refresh(member)
    assert member.role == UserRole.ADMIN


async def test_demote_an_admin_when_another_admin_remains(client, admin_headers, factory):
    other_admin = await factory.user(email="other-admin@example.com", role=UserRole.ADMIN)

    response = await client.patch(
        f"/team/members/{other_admin.id}/role", headers=admin_headers, json={"role": "member"}
    )

    assert response.status_code == 200
    assert response.json()["role"] == "member"


async def test_cannot_demote_the_last_remaining_admin(client, factory):
    """The guard counts *active* admins, so the setup deactivates the acting
    admin: exactly one active admin is left, and demoting it would leave the
    organisation with nobody who can administer it."""

    last_admin = await factory.user(email="only@example.com", role=UserRole.ADMIN)
    acting = await factory.user(email="acting@example.com", role=UserRole.ADMIN)
    acting.is_active = False
    await factory.session.commit()

    response = await client.patch(
        f"/team/members/{last_admin.id}/role", headers=auth_headers(acting), json={"role": "member"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot remove the last admin"


async def test_cannot_change_your_own_role(client, admin):
    response = await client.patch(
        f"/team/members/{admin.id}/role", headers=auth_headers(admin), json={"role": "member"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot change your own role"


async def test_change_role_404s_for_an_unknown_member(client, admin_headers):
    response = await client.patch(
        "/team/members/999999/role", headers=admin_headers, json={"role": "member"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Team member not found"


async def test_change_role_rejects_an_unknown_role(client, admin_headers, factory):
    member = await factory.user(email="badrole@example.com")

    response = await client.patch(
        f"/team/members/{member.id}/role", headers=admin_headers, json={"role": "wizard"}
    )

    assert response.status_code == 422


async def test_change_role_is_forbidden_for_members(client, member_headers, factory):
    target = await factory.user(email="target@example.com")

    response = await client.patch(
        f"/team/members/{target.id}/role", headers=member_headers, json={"role": "org_admin"}
    )

    assert response.status_code == 403


# ------------------------------------------------------------------
# PATCH /team/members/{id}/status
# ------------------------------------------------------------------

async def test_deactivate_a_member_blocks_their_login(client, admin_headers, factory):
    from helpers import TEST_PASSWORD

    member = await factory.user(email="toggle@example.com")

    response = await client.patch(
        f"/team/members/{member.id}/status", headers=admin_headers, json={"is_active": False}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"

    login = await client.post(
        "/auth/login", json={"email": member.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 403


async def test_reactivate_a_member_restores_their_login(client, admin_headers, factory):
    from helpers import TEST_PASSWORD

    member = await factory.user(email="restore@example.com", is_active=False)

    response = await client.patch(
        f"/team/members/{member.id}/status", headers=admin_headers, json={"is_active": True}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "active"

    login = await client.post(
        "/auth/login", json={"email": member.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200


async def test_setting_the_status_a_member_already_has_is_a_no_op(client, admin_headers, factory):
    member = await factory.user(email="idempotent@example.com")

    first = await client.patch(
        f"/team/members/{member.id}/status", headers=admin_headers, json={"is_active": True}
    )
    second = await client.patch(
        f"/team/members/{member.id}/status", headers=admin_headers, json={"is_active": True}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "active"


async def test_cannot_deactivate_your_own_account(client, admin):
    response = await client.patch(
        f"/team/members/{admin.id}/status", headers=auth_headers(admin), json={"is_active": False}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot deactivate your own account"


async def test_cannot_deactivate_the_last_admin(client, factory):
    last_admin = await factory.user(email="last@example.com", role=UserRole.ADMIN)
    actor = await factory.user(email="actor2@example.com", role=UserRole.ADMIN)
    actor.is_active = False
    await factory.session.commit()

    response = await client.patch(
        f"/team/members/{last_admin.id}/status",
        headers=auth_headers(actor),
        json={"is_active": False},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot remove the last admin"


async def test_change_status_404s_for_an_unknown_member(client, admin_headers):
    response = await client.patch(
        "/team/members/999999/status", headers=admin_headers, json={"is_active": False}
    )
    assert response.status_code == 404


async def test_change_status_requires_the_flag(client, admin_headers, factory):
    member = await factory.user(email="noflag@example.com")

    response = await client.patch(
        f"/team/members/{member.id}/status", headers=admin_headers, json={}
    )

    assert response.status_code == 422


async def test_change_status_is_forbidden_for_members(client, member_headers, factory):
    target = await factory.user(email="target2@example.com")

    response = await client.patch(
        f"/team/members/{target.id}/status", headers=member_headers, json={"is_active": False}
    )

    assert response.status_code == 403


# ------------------------------------------------------------------
# DELETE /team/members/{id}
# ------------------------------------------------------------------

async def test_delete_member_soft_deletes_and_keeps_them_listed(client, admin, factory, db):
    member = await factory.user(email="removeme@example.com")

    response = await client.delete(f"/team/members/{member.id}", headers=auth_headers(admin))

    assert response.status_code == 204
    await db.refresh(member)
    assert member.is_active is False

    listing = await client.get("/team/members", headers=auth_headers(admin))
    statuses = {row["email"]: row["status"] for row in listing.json()["data"]}
    assert statuses["removeme@example.com"] == "inactive"


async def test_delete_member_is_not_repeatable(client, admin_headers, factory):
    member = await factory.user(email="twice@example.com")

    first = await client.delete(f"/team/members/{member.id}", headers=admin_headers)
    second = await client.delete(f"/team/members/{member.id}", headers=admin_headers)

    assert first.status_code == 204
    assert second.status_code == 404


async def test_cannot_delete_your_own_account(client, admin):
    response = await client.delete(f"/team/members/{admin.id}", headers=auth_headers(admin))

    assert response.status_code == 400
    assert response.json()["detail"] == "You cannot delete your own account"


async def test_cannot_delete_the_last_admin(client, factory):
    last_admin = await factory.user(email="lastadmin@example.com", role=UserRole.ADMIN)
    actor = await factory.user(email="actor3@example.com", role=UserRole.ADMIN)
    actor.is_active = False
    await factory.session.commit()

    response = await client.delete(f"/team/members/{last_admin.id}", headers=auth_headers(actor))

    assert response.status_code == 400
    assert response.json()["detail"] == "Cannot remove the last admin"


async def test_delete_member_404s_for_an_unknown_id(client, admin_headers):
    response = await client.delete("/team/members/999999", headers=admin_headers)
    assert response.status_code == 404


async def test_delete_member_is_forbidden_for_members(client, member_headers, factory):
    target = await factory.user(email="target3@example.com")

    response = await client.delete(f"/team/members/{target.id}", headers=member_headers)

    assert response.status_code == 403
