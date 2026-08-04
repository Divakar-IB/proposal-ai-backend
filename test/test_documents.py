"""/document — knowledge-base upload (create + edit through one endpoint),
listing/filtering, retrieval and delete-with-cleanup."""

import pytest
from helpers import auth_headers, upload

from database.crud import get_knowledge_document_by_id
from database.db_enum import DocumentAvailability, IngestionStatus
from database.models import KnowledgeChunk
from sqlalchemy import func, select


async def create_document(client, headers, *, category_id, name="Case Study", **extra):
    data = {"document_name": name, "category_id": str(category_id), **extra}
    return await client.post(
        "/document/upload", headers=headers, data=data, files={"file": upload("case-study.pdf")}
    )


# ------------------------------------------------------------------
# POST /document/upload — create
# ------------------------------------------------------------------

async def test_upload_creates_a_document(client, member, factory, fake_s3, stub_background_pipelines):
    category = await factory.category(name="Case Studies")

    response = await create_document(client, auth_headers(member), category_id=category.id)

    assert response.status_code == 200
    body = response.json()
    assert body["document_name"] == "Case Study"
    assert body["file_name"] == "case-study.pdf"
    assert body["extension"] == "pdf"
    assert body["category_id"] == category.id
    assert body["category_name"] == "Case Studies"
    assert body["user_id"] == member.id
    assert body["version"] == 1
    assert body["status"] == IngestionStatus.PENDING.value
    assert body["availability_status"] == DocumentAvailability.ACTIVE.value
    assert body["url"].startswith("https://s3.test/")

    assert len(fake_s3.uploaded) == 1
    assert fake_s3.uploaded[0].startswith(f"input/knowledge/{member.id}/{category.id}/")
    # Ingestion is deferred to a background task, not done in the request.
    assert stub_background_pipelines["process_knowledge_document"] == [body["id"]]


async def test_upload_records_the_uploader_from_the_token_not_the_form(
    client, member, factory
):
    """Identity always comes from `current_user`; a user_id in the body is
    ignored rather than trusted."""

    category = await factory.category()

    response = await create_document(
        client, auth_headers(member), category_id=category.id, user_id="999999"
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == member.id


async def test_upload_stores_tags(client, member, factory):
    category = await factory.category()

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={
            "document_name": "Tagged",
            "category_id": str(category.id),
            "tags": ["aws", "migration"],
        },
        files={"file": upload("tagged.pdf")},
    )

    assert response.status_code == 200
    assert response.json()["tags"] == ["aws", "migration"]


async def test_upload_accepts_an_explicit_availability_status(client, member, factory):
    category = await factory.category()

    response = await create_document(
        client, auth_headers(member), category_id=category.id, availability_status="inactive"
    )

    assert response.status_code == 200
    assert response.json()["availability_status"] == "inactive"


@pytest.mark.parametrize(
    "omit, expected_in_detail",
    [
        ("document_name", "document_name"),
        ("category_id", "category_id"),
        ("file", "file"),
    ],
)
async def test_upload_requires_name_category_and_file_on_create(
    client, member, factory, omit, expected_in_detail
):
    category = await factory.category()
    data = {"document_name": "X", "category_id": str(category.id)}
    files = {"file": upload()}
    data.pop(omit, None)
    if omit == "file":
        files = {}

    response = await client.post(
        "/document/upload", headers=auth_headers(member), data=data, files=files or None
    )

    assert response.status_code == 422
    assert expected_in_detail in str(response.json()["detail"])


async def test_upload_treats_a_blank_filename_part_as_no_file(client, member, factory, fake_s3):
    """A browser (and Swagger) still submits an untouched file input as a part
    with a blank filename — it must not become a 0-byte object under that name.
    The handler drops it, so this lands on the "file is required" branch."""

    category = await factory.category()

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_name": "X", "category_id": str(category.id)},
        files={"file": (" ", b"", "application/octet-stream")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "file is required when creating a document. To edit an existing one, pass document_id."
    )
    assert fake_s3.uploaded == []


async def test_upload_404s_for_an_unknown_category(client, member_headers):
    response = await create_document(client, member_headers, category_id=999999)

    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


async def test_upload_404s_for_a_soft_deleted_category(client, member, factory):
    category = await factory.category(is_active=False)

    response = await create_document(client, auth_headers(member), category_id=category.id)

    assert response.status_code == 404


async def test_upload_502s_and_writes_no_row_when_s3_fails(client, member, factory, db, fake_s3):
    """S3 first, database second — a failed upload must not leave a document
    row pointing at an object that was never stored."""

    category = await factory.category()
    fake_s3.upload_error = RuntimeError("bucket unreachable")

    response = await create_document(client, auth_headers(member), category_id=category.id)

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to upload file to storage. Please try again."
    listing = await client.get("/document/list", headers=auth_headers(member))
    assert listing.json()["total"] == 0


async def test_upload_requires_a_token(client, factory):
    category = await factory.category()
    response = await create_document(client, {}, category_id=category.id)
    assert response.status_code == 401


# ------------------------------------------------------------------
# POST /document/upload — edit (document_id supplied)
# ------------------------------------------------------------------

async def test_edit_updates_metadata_without_touching_the_file(
    client, member, factory, db, fake_s3, stub_background_pipelines
):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category, title="Before")

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={
            "document_id": str(document.id),
            "document_name": "After",
            "description": "Updated description",
        },
    )

    assert response.status_code == 200
    assert response.json()["document_name"] == "After"
    assert response.json()["description"] == "Updated description"
    assert response.json()["version"] == 1  # unchanged: no new file
    assert fake_s3.uploaded == []
    # No re-chunk/re-embed when the bytes did not change.
    assert stub_background_pipelines["process_knowledge_document"] == []
    await db.refresh(document)
    assert document.title == "After"


async def test_edit_replacing_the_file_bumps_the_version_and_reindexes(
    client, member, factory, db, fake_s3, stub_background_pipelines
):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)
    original_path = document.file_path

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_id": str(document.id)},
        files={"file": upload("v2.pdf")},
    )

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["file_name"] == "v2.pdf"
    assert len(fake_s3.uploaded) == 1
    assert original_path in fake_s3.deleted  # old object cleaned up
    assert stub_background_pipelines["process_knowledge_document"] == [document.id]
    await db.refresh(document)
    assert document.file_path != original_path


async def test_edit_can_move_a_document_to_another_category(client, member, factory):
    source = await factory.category(name="Source")
    destination = await factory.category(name="Destination")
    document = await factory.knowledge_document(user=member, category=source)

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_id": str(document.id), "category_id": str(destination.id)},
    )

    assert response.status_code == 200
    assert response.json()["category_id"] == destination.id
    assert response.json()["category_name"] == "Destination"


async def test_edit_404s_for_an_unknown_category(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_id": str(document.id), "category_id": "999999"},
    )

    assert response.status_code == 404


async def test_edit_404s_for_an_unknown_document(client, member_headers):
    response = await client.post(
        "/document/upload", headers=member_headers, data={"document_id": "999999", "document_name": "X"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


async def test_edit_404s_for_a_soft_deleted_document(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category, is_active=False)

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_id": str(document.id), "document_name": "X"},
    )

    assert response.status_code == 404


async def test_edit_with_no_changes_is_a_no_op(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category, title="Same")

    response = await client.post(
        "/document/upload", headers=auth_headers(member), data={"document_id": str(document.id)}
    )

    assert response.status_code == 200
    assert response.json()["document_name"] == "Same"
    assert response.json()["version"] == 1


async def test_edit_502s_when_the_replacement_upload_fails(client, member, factory, db, fake_s3):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)
    original_path = document.file_path
    fake_s3.upload_error = RuntimeError("bucket unreachable")

    response = await client.post(
        "/document/upload",
        headers=auth_headers(member),
        data={"document_id": str(document.id)},
        files={"file": upload("v2.pdf")},
    )

    assert response.status_code == 502
    await db.refresh(document)
    assert document.file_path == original_path  # still points at the good object
    assert document.version == 1
    assert fake_s3.deleted == []


# ------------------------------------------------------------------
# GET /document/list
# ------------------------------------------------------------------

async def test_list_documents_returns_pagination_metadata(client, member, factory):
    category = await factory.category()
    for _ in range(3):
        await factory.knowledge_document(user=member, category=category)

    response = await client.get("/document/list?page=1&limit=2", headers=auth_headers(member))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert body["page"] == 1
    assert body["limit"] == 2
    assert len(body["data"]) == 2


async def test_list_documents_is_empty_rather_than_404_when_nothing_matches(client, member_headers):
    response = await client.get("/document/list", headers=member_headers)

    assert response.status_code == 200
    assert response.json()["data"] == []
    assert response.json()["total"] == 0


async def test_list_documents_filters_by_category(client, member, factory):
    wanted = await factory.category(name="Wanted")
    other = await factory.category(name="Other")
    await factory.knowledge_document(user=member, category=wanted, title="Keep")
    await factory.knowledge_document(user=member, category=other, title="Drop")

    response = await client.get(
        f"/document/list?category_id={wanted.id}", headers=auth_headers(member)
    )

    assert [row["document_name"] for row in response.json()["data"]] == ["Keep"]


async def test_list_documents_searches_titles_case_insensitively(client, member, factory):
    category = await factory.category()
    await factory.knowledge_document(user=member, category=category, title="Cloud Migration Study")
    await factory.knowledge_document(user=member, category=category, title="Security Audit")

    response = await client.get("/document/list?search=migration", headers=auth_headers(member))

    assert [row["document_name"] for row in response.json()["data"]] == ["Cloud Migration Study"]


async def test_list_documents_filters_by_availability_status(client, member, factory):
    category = await factory.category()
    await factory.knowledge_document(
        user=member, category=category, title="Live", availability_status=DocumentAvailability.ACTIVE
    )
    await factory.knowledge_document(
        user=member,
        category=category,
        title="Shelved",
        availability_status=DocumentAvailability.INACTIVE,
    )

    response = await client.get("/document/list?status=inactive", headers=auth_headers(member))

    assert [row["document_name"] for row in response.json()["data"]] == ["Shelved"]


async def test_list_documents_hides_proposal_derived_documents_by_default(client, member, factory):
    category = await factory.category()
    proposal = await factory.proposal(user=member)
    await factory.knowledge_document(user=member, category=category, title="Manual")
    await factory.knowledge_document(
        user=member, category=category, title="From Proposal", source_proposal_id=proposal.id
    )

    default = await client.get("/document/list", headers=auth_headers(member))
    included = await client.get(
        "/document/list?include_generated=true", headers=auth_headers(member)
    )

    assert [row["document_name"] for row in default.json()["data"]] == ["Manual"]
    assert {row["document_name"] for row in included.json()["data"]} == {"Manual", "From Proposal"}


async def test_list_documents_excludes_soft_deleted_documents(client, member, factory):
    category = await factory.category()
    await factory.knowledge_document(user=member, category=category, title="Live")
    await factory.knowledge_document(user=member, category=category, title="Deleted", is_active=False)

    response = await client.get("/document/list", headers=auth_headers(member))

    assert [row["document_name"] for row in response.json()["data"]] == ["Live"]


async def test_list_documents_combines_filters(client, member, factory):
    wanted = await factory.category(name="Wanted")
    other = await factory.category(name="Other")
    await factory.knowledge_document(user=member, category=wanted, title="Cloud Report")
    await factory.knowledge_document(user=member, category=wanted, title="Security Report")
    await factory.knowledge_document(user=member, category=other, title="Cloud Notes")

    response = await client.get(
        f"/document/list?category_id={wanted.id}&search=cloud", headers=auth_headers(member)
    )

    assert [row["document_name"] for row in response.json()["data"]] == ["Cloud Report"]


async def test_list_documents_rejects_an_unknown_status_value(client, member_headers):
    response = await client.get("/document/list?status=archived", headers=member_headers)
    assert response.status_code == 422


async def test_list_documents_requires_a_token(client):
    response = await client.get("/document/list")
    assert response.status_code == 401


# ------------------------------------------------------------------
# GET /document/{id}
# ------------------------------------------------------------------

async def test_get_document(client, member, factory):
    category = await factory.category(name="Refs")
    document = await factory.knowledge_document(user=member, category=category, title="Single")

    response = await client.get(f"/document/{document.id}", headers=auth_headers(member))

    assert response.status_code == 200
    assert response.json()["id"] == document.id
    assert response.json()["document_name"] == "Single"
    assert response.json()["category_name"] == "Refs"


async def test_get_document_404s_for_an_unknown_id(client, member_headers):
    response = await client.get("/document/999999", headers=member_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found"


async def test_get_document_404s_for_a_soft_deleted_document(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category, is_active=False)

    response = await client.get(f"/document/{document.id}", headers=auth_headers(member))

    assert response.status_code == 404


async def test_the_list_route_is_not_swallowed_by_the_dynamic_path(client, member_headers):
    """/document/list is declared before /document/{document_id}; if that ever
    flips, "list" gets parsed as an id and this 422s."""

    response = await client.get("/document/list", headers=member_headers)
    assert response.status_code == 200


async def test_get_document_rejects_a_non_integer_id(client, member_headers):
    response = await client.get("/document/not-a-number", headers=member_headers)
    assert response.status_code == 422


# ------------------------------------------------------------------
# DELETE /document/{id}
# ------------------------------------------------------------------

async def test_delete_document_cleans_up_s3_pinecone_and_chunks(
    client, member, factory, db, fake_s3, stub_background_pipelines
):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)
    await factory.knowledge_chunk(document=document, chunk_index=0)
    await factory.knowledge_chunk(document=document, chunk_index=1)

    response = await client.delete(f"/document/{document.id}", headers=auth_headers(member))

    assert response.status_code == 204
    assert document.file_path in fake_s3.deleted
    assert stub_background_pipelines["delete_document_vectors"] == [document.id]

    remaining = await db.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.knowledge_document_id == document.id)
    )
    assert remaining == 0
    assert await get_knowledge_document_by_id(db, document.id) is None  # soft-deleted


async def test_delete_document_404s_for_an_unknown_id(client, member_headers):
    response = await client.delete("/document/999999", headers=member_headers)
    assert response.status_code == 404


async def test_delete_document_is_not_repeatable(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)

    first = await client.delete(f"/document/{document.id}", headers=auth_headers(member))
    second = await client.delete(f"/document/{document.id}", headers=auth_headers(member))

    assert first.status_code == 204
    assert second.status_code == 404


async def test_delete_document_requires_a_token(client, member, factory):
    category = await factory.category()
    document = await factory.knowledge_document(user=member, category=category)

    response = await client.delete(f"/document/{document.id}")

    assert response.status_code == 401
