"""/profile — the current user's own record, resolved from the JWT."""

from helpers import auth_headers

from authentication.jwt_handler import create_access_token
from database.db_enum import UserRole


async def test_get_profile_returns_the_token_owner(client, factory):
    user = await factory.user(
        email="me@example.com", role=UserRole.ADMIN, full_name="Ada Lovelace", designation="CTO"
    )

    response = await client.get("/profile", headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json() == {
        "id": user.id,
        "email": "me@example.com",
        "full_name": "Ada Lovelace",
        "designation": "CTO",
        "role": "org_admin",
    }


async def test_get_profile_404s_when_the_token_points_at_no_row(client):
    """A structurally valid token for a user that no longer exists must 404,
    not 500."""

    token = create_access_token(user_id=999_999, email="ghost@example.com", role="member")

    response = await client.get("/profile", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


async def test_get_profile_requires_a_token(client):
    response = await client.get("/profile")
    assert response.status_code == 401


async def test_update_profile_sets_both_fields(client, factory, db):
    user = await factory.user(email="update@example.com")

    response = await client.put(
        "/profile",
        headers=auth_headers(user),
        json={"full_name": "Grace Hopper", "designation": "Rear Admiral"},
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "Grace Hopper"
    await db.refresh(user)
    assert user.designation == "Rear Admiral"


async def test_update_profile_leaves_omitted_fields_untouched(client, factory):
    """`exclude_unset` semantics: a field absent from the body is not a clear."""

    user = await factory.user(
        email="partial@example.com", full_name="Original Name", designation="Original Title"
    )

    response = await client.put(
        "/profile", headers=auth_headers(user), json={"full_name": "New Name"}
    )

    assert response.status_code == 200
    assert response.json()["full_name"] == "New Name"
    assert response.json()["designation"] == "Original Title"


async def test_update_profile_clears_a_field_sent_as_null(client, factory):
    user = await factory.user(email="clear@example.com", full_name="Name", designation="Title")

    response = await client.put(
        "/profile", headers=auth_headers(user), json={"designation": None}
    )

    assert response.status_code == 200
    assert response.json()["designation"] is None
    assert response.json()["full_name"] == "Name"


async def test_update_profile_with_an_empty_body_is_a_no_op(client, factory):
    user = await factory.user(email="noop@example.com", full_name="Name", designation="Title")

    response = await client.put("/profile", headers=auth_headers(user), json={})

    assert response.status_code == 200
    assert response.json()["full_name"] == "Name"
    assert response.json()["designation"] == "Title"


async def test_update_profile_cannot_change_email_or_role(client, factory, db):
    """Email is the login id and role is an admin decision — both are outside
    UpdateProfileRequest, so extra keys are simply dropped."""

    user = await factory.user(email="fixed@example.com", role=UserRole.USER)

    response = await client.put(
        "/profile",
        headers=auth_headers(user),
        json={"full_name": "Someone", "email": "hijack@example.com", "role": "org_admin"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "fixed@example.com"
    assert response.json()["role"] == "member"
    await db.refresh(user)
    assert user.email == "fixed@example.com"
    assert user.role == UserRole.USER


async def test_update_profile_rejects_wrong_field_types(client, factory):
    user = await factory.user(email="types@example.com")

    response = await client.put(
        "/profile", headers=auth_headers(user), json={"full_name": {"nested": "object"}}
    )

    assert response.status_code == 422


async def test_update_profile_requires_a_token(client):
    response = await client.put("/profile", json={"full_name": "X"})
    assert response.status_code == 401


async def test_one_user_cannot_read_another_users_profile(client, factory):
    """Identity comes only from the token — there is no user_id parameter to
    tamper with."""

    first = await factory.user(email="first@example.com")
    second = await factory.user(email="second@example.com")

    response = await client.get(f"/profile?user_id={second.id}", headers=auth_headers(first))

    assert response.status_code == 200
    assert response.json()["email"] == "first@example.com"
