"""/category — create/update through one POST, listing with document counts,
and soft delete guarded by document usage."""

import pytest
from helpers import auth_headers

from database.crud import get_category_by_name_including_deleted

# ------------------------------------------------------------------
# POST /category — create
# ------------------------------------------------------------------


async def test_create_category(client, member_headers, db):
    response = await client.post(
        "/category", headers=member_headers, json={"name": "Cloud & DevOps", "description": "CI/CD"}
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Category created successfully"}
    created = await get_category_by_name_including_deleted(db, "Cloud & DevOps")
    assert created is not None
    assert created.description == "CI/CD"


async def test_create_category_rejects_a_duplicate_active_name(client, member_headers, factory):
    await factory.category(name="Backend")

    response = await client.post("/category", headers=member_headers, json={"name": "Backend", "description": "again"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Category name already exists"


async def test_create_category_revives_a_soft_deleted_name(client, member_headers, factory, db):
    """Category.name is UNIQUE and deletion is a soft delete, so the only way a
    name can be reused is by reviving the hidden row."""

    deleted = await factory.category(name="Archived", description="old", is_active=False)

    response = await client.post("/category", headers=member_headers, json={"name": "Archived", "description": "new"})

    assert response.status_code == 200
    assert response.json() == {"message": "Category created successfully"}
    await db.refresh(deleted)
    assert deleted.is_active is True
    assert deleted.description == "new"

    listing = await client.get("/category/list", headers=member_headers)
    assert [row["name"] for row in listing.json()["data"]] == ["Archived"]


async def test_create_category_requires_a_description(client, member_headers):
    response = await client.post("/category", headers=member_headers, json={"name": "NoDesc"})
    assert response.status_code == 422


async def test_create_category_requires_a_name(client, member_headers):
    response = await client.post("/category", headers=member_headers, json={"description": "x"})
    assert response.status_code == 422


async def test_create_category_requires_a_token(client):
    response = await client.post("/category", json={"name": "X", "description": "y"})
    assert response.status_code == 401


# ------------------------------------------------------------------
# POST /category — update (id supplied)
# ------------------------------------------------------------------


async def test_update_category(client, member_headers, factory, db):
    category = await factory.category(name="Old Name", description="old")

    response = await client.post(
        "/category",
        headers=member_headers,
        json={"id": category.id, "name": "New Name", "description": "new"},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Category updated successfully"}
    await db.refresh(category)
    assert category.name == "New Name"
    assert category.description == "new"


async def test_update_category_404s_for_an_unknown_id(client, member_headers):
    response = await client.post(
        "/category", headers=member_headers, json={"id": 999999, "name": "X", "description": "y"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


async def test_update_category_rejects_a_name_taken_by_another_category(client, member_headers, factory):
    await factory.category(name="Taken")
    category = await factory.category(name="Mine")

    response = await client.post(
        "/category",
        headers=member_headers,
        json={"id": category.id, "name": "Taken", "description": "x"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Category name already exists"


async def test_update_category_can_keep_its_own_name(client, member_headers, factory, db):
    """The uniqueness check excludes the row being edited, so re-saving the
    form without renaming must not 400."""

    category = await factory.category(name="Stable", description="before")

    response = await client.post(
        "/category",
        headers=member_headers,
        json={"id": category.id, "name": "Stable", "description": "after"},
    )

    assert response.status_code == 200
    await db.refresh(category)
    assert category.description == "after"


async def test_renaming_onto_a_soft_deleted_name_currently_500s(client, member_headers, factory):
    """Renaming onto a soft-deleted category's name blows up on the DB UNIQUE
    constraint, which the error middleware reports as an opaque 503.

    The create branch handles this case (it revives the hidden row); the update
    branch's duplicate check filters `is_active.is_(True)`, so the name slips
    past it and only the database stops it. Pinned here as the *current*
    behaviour — see the xfail below for what it should be.
    """

    await factory.category(name="Retired", is_active=False)
    category = await factory.category(name="Active One")

    response = await client.post(
        "/category",
        headers=member_headers,
        json={"id": category.id, "name": "Retired", "description": "x"},
    )

    assert response.status_code == 503


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: router/category.py's update branch checks for duplicates with "
        "`Category.is_active.is_(True)`, so renaming onto a soft-deleted category's "
        "name reaches the DB and raises IntegrityError -> 503. It should be rejected "
        "with a 4xx (or revive/merge the hidden row, as the create branch does)."
    ),
)
async def test_renaming_onto_a_soft_deleted_name_should_be_a_client_error(client, member_headers, factory):
    await factory.category(name="Retired", is_active=False)
    category = await factory.category(name="Active One")

    response = await client.post(
        "/category",
        headers=member_headers,
        json={"id": category.id, "name": "Retired", "description": "x"},
    )

    assert 400 <= response.status_code < 500


# ------------------------------------------------------------------
# GET /category/list
# ------------------------------------------------------------------


async def test_list_categories_with_document_counts(client, member, factory):
    first = await factory.category(name="With Docs")
    await factory.category(name="Empty")
    await factory.knowledge_document(user=member, category=first)
    await factory.knowledge_document(user=member, category=first)

    response = await client.get("/category/list", headers=auth_headers(member))

    assert response.status_code == 200
    counts = {row["name"]: row["document_count"] for row in response.json()["data"]}
    assert counts == {"With Docs": 2, "Empty": 0}


async def test_list_categories_ignores_soft_deleted_categories(client, member_headers, factory):
    await factory.category(name="Visible")
    await factory.category(name="Hidden", is_active=False)

    response = await client.get("/category/list", headers=member_headers)

    assert [row["name"] for row in response.json()["data"]] == ["Visible"]


async def test_list_categories_counts_only_active_documents(client, member, factory):
    category = await factory.category(name="Mixed")
    await factory.knowledge_document(user=member, category=category)
    await factory.knowledge_document(user=member, category=category, is_active=False)

    response = await client.get("/category/list", headers=auth_headers(member))

    assert response.json()["data"][0]["document_count"] == 1


async def test_list_categories_is_empty_when_there_are_none(client, member_headers):
    response = await client.get("/category/list", headers=member_headers)

    assert response.status_code == 200
    assert response.json() == {"data": []}


async def test_list_categories_requires_a_token(client):
    response = await client.get("/category/list")
    assert response.status_code == 401


# ------------------------------------------------------------------
# DELETE /category/{id}
# ------------------------------------------------------------------


async def test_delete_category_soft_deletes_it(client, member_headers, factory, db):
    category = await factory.category(name="Doomed")

    response = await client.delete(f"/category/{category.id}", headers=member_headers)

    assert response.status_code == 204
    await db.refresh(category)
    assert category.is_active is False

    listing = await client.get("/category/list", headers=member_headers)
    assert listing.json()["data"] == []


async def test_delete_category_404s_for_an_unknown_id(client, member_headers):
    response = await client.delete("/category/999999", headers=member_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


async def test_delete_category_404s_when_already_deleted(client, member_headers, factory):
    category = await factory.category(name="Gone", is_active=False)

    response = await client.delete(f"/category/{category.id}", headers=member_headers)

    assert response.status_code == 404


async def test_delete_category_409s_while_documents_still_use_it(client, member, factory):
    """KnowledgeDocument.category_id is a non-nullable FK and the documents'
    Pinecone metadata carries the category id, so the category cannot quietly
    disappear from under them."""

    category = await factory.category(name="In Use")
    await factory.knowledge_document(user=member, category=category)
    await factory.knowledge_document(user=member, category=category)

    response = await client.delete(f"/category/{category.id}", headers=auth_headers(member))

    assert response.status_code == 409
    assert "2 document(s)" in response.json()["detail"]
    assert "In Use" in response.json()["detail"]


async def test_delete_category_ignores_soft_deleted_documents(client, member, factory):
    category = await factory.category(name="Only Deleted Docs")
    await factory.knowledge_document(user=member, category=category, is_active=False)

    response = await client.delete(f"/category/{category.id}", headers=auth_headers(member))

    assert response.status_code == 204


@pytest.mark.parametrize("category_id", ["abc", "1.5"])
async def test_delete_category_rejects_a_non_integer_id(client, member_headers, category_id):
    response = await client.delete(f"/category/{category_id}", headers=member_headers)
    assert response.status_code == 422


async def test_delete_category_requires_a_token(client, factory):
    category = await factory.category()
    response = await client.delete(f"/category/{category.id}")
    assert response.status_code == 401
