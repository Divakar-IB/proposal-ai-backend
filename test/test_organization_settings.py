"""/organization-settings — the single-row branding profile plus its dedicated
logo upload/remove flow. Admin only."""

import pytest
from helpers import upload

from database.crud import get_organization_settings


# ------------------------------------------------------------------
# GET /organization-settings
# ------------------------------------------------------------------

async def test_get_settings_returns_an_empty_shape_when_no_row_exists(client, admin_headers):
    """The Settings page always has something to render, so a missing row is an
    all-null response rather than a 404."""

    response = await client.get("/organization-settings", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "id": None,
        "organization_name": None,
        "contact_email": None,
        "default_signee_name": None,
        "default_signee_designation": None,
        "proposal_naming_template": None,
        "logo_url": None,
        "created_at": None,
        "updated_at": None,
    }


async def test_get_settings_returns_the_stored_row(client, admin_headers, factory):
    await factory.organization_settings(
        organization_name="Innoboon", contact_email="hello@innoboon.com", default_signee_name="Ada"
    )

    response = await client.get("/organization-settings", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["organization_name"] == "Innoboon"
    assert body["contact_email"] == "hello@innoboon.com"
    assert body["default_signee_name"] == "Ada"
    assert body["logo_url"] is None


async def test_get_settings_presigns_the_logo(client, admin_headers, factory):
    await factory.organization_settings(logo_path="input/organization/logo/abc.png")

    response = await client.get("/organization-settings", headers=admin_headers)

    assert response.json()["logo_url"] == "https://s3.test/input/organization/logo/abc.png?signed=1"


async def test_get_settings_is_forbidden_for_members(client, member_headers):
    response = await client.get("/organization-settings", headers=member_headers)
    assert response.status_code == 403


async def test_get_settings_requires_a_token(client):
    response = await client.get("/organization-settings")
    assert response.status_code == 401


# ------------------------------------------------------------------
# PUT /organization-settings
# ------------------------------------------------------------------

async def test_put_settings_creates_the_row(client, admin_headers, db):
    response = await client.put(
        "/organization-settings",
        headers=admin_headers,
        json={"organization_name": "Innoboon", "contact_email": "hi@innoboon.com"},
    )

    assert response.status_code == 200
    assert response.json()["organization_name"] == "Innoboon"
    assert response.json()["id"] is not None
    assert await get_organization_settings(db) is not None


async def test_put_settings_updates_the_existing_row_rather_than_adding_one(
    client, admin_headers, factory, db
):
    settings = await factory.organization_settings(organization_name="Old Name")

    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"organization_name": "New Name"}
    )

    assert response.status_code == 200
    assert response.json()["id"] == settings.id
    await db.refresh(settings)
    assert settings.organization_name == "New Name"


async def test_put_settings_leaves_omitted_fields_untouched(client, admin_headers, factory):
    await factory.organization_settings(
        organization_name="Innoboon", default_signee_name="Ada", contact_email="a@b.com"
    )

    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"organization_name": "Renamed"}
    )

    assert response.status_code == 200
    assert response.json()["organization_name"] == "Renamed"
    assert response.json()["default_signee_name"] == "Ada"


async def test_put_settings_clears_a_field_sent_as_null(client, admin_headers, factory):
    """Re-saving the form with a field cleared has to actually clear it, not
    silently keep the old value."""

    await factory.organization_settings(organization_name="Innoboon", default_signee_name="Ada")

    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"default_signee_name": None}
    )

    assert response.status_code == 200
    assert response.json()["default_signee_name"] is None
    assert response.json()["organization_name"] == "Innoboon"


async def test_put_settings_normalises_the_contact_email(client, admin_headers):
    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"contact_email": "Hello@Innoboon.COM"}
    )

    assert response.status_code == 200
    assert response.json()["contact_email"] == "Hello@innoboon.com"


async def test_put_settings_treats_an_empty_contact_email_as_null(client, admin_headers):
    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"contact_email": ""}
    )

    assert response.status_code == 200
    assert response.json()["contact_email"] is None


async def test_put_settings_rejects_an_invalid_contact_email(client, admin_headers):
    response = await client.put(
        "/organization-settings", headers=admin_headers, json={"contact_email": "not-an-email"}
    )

    assert response.status_code == 422


async def test_put_settings_with_an_empty_body_creates_an_all_null_row(client, admin_headers, db):
    response = await client.put("/organization-settings", headers=admin_headers, json={})

    assert response.status_code == 200
    assert response.json()["id"] is not None
    assert response.json()["organization_name"] is None
    assert await get_organization_settings(db) is not None


async def test_put_settings_is_forbidden_for_members(client, member_headers):
    response = await client.put(
        "/organization-settings", headers=member_headers, json={"organization_name": "X"}
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# POST /organization-settings/logo
# ------------------------------------------------------------------

async def test_upload_logo_stores_it_and_returns_a_presigned_url(client, admin_headers, fake_s3):
    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload("logo.png", b"\x89PNG fake", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["logo_url"].startswith("https://s3.test/input/organization/logo/")
    assert len(fake_s3.uploaded) == 1


async def test_upload_logo_replaces_the_old_object_only_after_the_new_one_lands(
    client, admin_headers, factory, fake_s3
):
    await factory.organization_settings(logo_path="input/organization/logo/old.png")

    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload("new.png", b"\x89PNG fake", "image/png")},
    )

    assert response.status_code == 200
    assert fake_s3.deleted == ["input/organization/logo/old.png"]
    assert len(fake_s3.uploaded) == 1


async def test_upload_logo_survives_a_failed_cleanup_of_the_old_object(
    client, admin_headers, factory, fake_s3, db
):
    """Failing to delete the replaced object leaves an orphan in the bucket but
    must not fail the request — the new logo is already live."""

    await factory.organization_settings(logo_path="input/organization/logo/old.png")
    fake_s3.delete_error = RuntimeError("s3 delete failed")

    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload("new.png", b"\x89PNG fake", "image/png")},
    )

    assert response.status_code == 200
    settings = await get_organization_settings(db)
    assert settings.logo_path != "input/organization/logo/old.png"


@pytest.mark.parametrize(
    "filename, content_type",
    [
        ("logo.gif", "image/gif"),
        ("logo.svg", "image/svg+xml"),
        ("logo.png", "text/html"),
        ("logo.pdf", "application/pdf"),
        ("noextension", "image/png"),
    ],
    ids=["gif", "svg", "png-name-wrong-type", "pdf", "no-extension"],
)
async def test_upload_logo_rejects_non_image_files(client, admin_headers, filename, content_type):
    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload(filename, b"data", content_type)},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Logo must be a PNG or JPEG image."


@pytest.mark.parametrize("filename", ["logo.jpg", "logo.jpeg", "LOGO.PNG"])
async def test_upload_logo_accepts_png_and_jpeg(client, admin_headers, filename):
    content_type = "image/png" if filename.lower().endswith("png") else "image/jpeg"

    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload(filename, b"image-bytes", content_type)},
    )

    assert response.status_code == 200


async def test_upload_logo_rejects_files_over_2mb(client, admin_headers):
    oversized = b"x" * (2 * 1024 * 1024 + 1)

    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload("big.png", oversized, "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Logo must be 2MB or smaller."


async def test_upload_logo_502s_when_s3_fails(client, admin_headers, fake_s3):
    fake_s3.upload_error = RuntimeError("bucket unreachable")

    response = await client.post(
        "/organization-settings/logo",
        headers=admin_headers,
        files={"file": upload("logo.png", b"\x89PNG", "image/png")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to upload logo to storage. Please try again."


async def test_upload_logo_requires_a_file(client, admin_headers):
    response = await client.post("/organization-settings/logo", headers=admin_headers)
    assert response.status_code == 422


async def test_upload_logo_is_forbidden_for_members(client, member_headers):
    response = await client.post(
        "/organization-settings/logo",
        headers=member_headers,
        files={"file": upload("logo.png", b"\x89PNG", "image/png")},
    )
    assert response.status_code == 403


# ------------------------------------------------------------------
# DELETE /organization-settings/logo
# ------------------------------------------------------------------

async def test_remove_logo_clears_the_path_and_deletes_the_object(
    client, admin_headers, factory, fake_s3, db
):
    settings = await factory.organization_settings(logo_path="input/organization/logo/abc.png")

    response = await client.delete("/organization-settings/logo", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["logo_url"] is None
    assert fake_s3.deleted == ["input/organization/logo/abc.png"]
    await db.refresh(settings)
    assert settings.logo_path is None


async def test_remove_logo_is_a_no_op_when_there_is_no_settings_row(client, admin_headers, fake_s3):
    """Deleting something that isn't there is not an error."""

    response = await client.delete("/organization-settings/logo", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["logo_url"] is None
    assert fake_s3.deleted == []


async def test_remove_logo_is_a_no_op_when_no_logo_is_set(client, admin_headers, factory, fake_s3):
    await factory.organization_settings(logo_path=None)

    response = await client.delete("/organization-settings/logo", headers=admin_headers)

    assert response.status_code == 200
    assert fake_s3.deleted == []


async def test_remove_logo_is_repeatable(client, admin_headers, factory):
    await factory.organization_settings(logo_path="input/organization/logo/abc.png")

    first = await client.delete("/organization-settings/logo", headers=admin_headers)
    second = await client.delete("/organization-settings/logo", headers=admin_headers)

    assert first.status_code == 200
    assert second.status_code == 200


async def test_remove_logo_502s_when_s3_delete_fails(client, admin_headers, factory, fake_s3, db):
    """Unlike the replace path, an explicit delete that cannot reach S3 is
    surfaced — the row is left pointing at the object so a retry can finish."""

    settings = await factory.organization_settings(logo_path="input/organization/logo/abc.png")
    fake_s3.delete_error = RuntimeError("s3 delete failed")

    response = await client.delete("/organization-settings/logo", headers=admin_headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to delete logo from storage. Please try again."
    await db.refresh(settings)
    assert settings.logo_path == "input/organization/logo/abc.png"


async def test_remove_logo_is_forbidden_for_members(client, member_headers):
    response = await client.delete("/organization-settings/logo", headers=member_headers)
    assert response.status_code == 403
