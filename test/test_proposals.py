"""/proposal — requirement-document intake, the streaming generate endpoint,
listing/stats, status transitions, delete, and export (download + email)."""

import pytest
from helpers import auth_headers, upload

from database.crud import get_proposal_by_id
from database.db_enum import DocumentStatus, GenerationMode, ProposalStatus
from generation.length_budget import MIN_PROPOSAL_PAGES


# ------------------------------------------------------------------
# POST /proposal/requirement-documents
# ------------------------------------------------------------------

async def test_upload_requirement_document_creates_a_proposal_and_runs_the_pipeline(
    client, member, fake_s3, stub_background_pipelines
):
    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme Corp", "proposal_name": "Acme RFP", "additional_context": "urgent"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["file_name"] == "rfp.pdf"
    assert body["extension"] == "pdf"
    assert body["client_name"] == "Acme Corp"
    assert body["proposal_name"] == "Acme RFP"
    assert body["additional_context"] == "urgent"
    assert body["status"] == DocumentStatus.PARSED.value
    assert body["summary"] == "Summary for rfp.pdf"
    assert body["capability_tags"] == [{"name": "Backend Development", "confidence": 0.9}]
    assert body["additional_documents"] == []
    assert body["user_id"] == member.id

    assert len(fake_s3.uploaded) == 1
    assert fake_s3.uploaded[0].startswith(f"input/requirements/{member.id}/")
    # The pipeline runs inline, not as a background task — the caller gets the
    # summary back in this same response.
    assert stub_background_pipelines["process_requirement_document_pipeline"] == [body["id"]]


async def test_upload_multiple_requirement_documents_in_order(client, member, stub_background_pipelines):
    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme Corp"},
        files=[("files", upload("first.pdf")), ("files", upload("second.pdf"))],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["file_name"] == "first.pdf"
    assert [extra["file_name"] for extra in body["additional_documents"]] == ["second.pdf"]
    assert len(stub_background_pipelines["process_requirement_document_pipeline"]) == 2


async def test_upload_requirement_document_auto_names_the_proposal(client, member, db):
    """With no explicit proposal_name, the title comes from the first parsed
    document's project_title (see proposal_naming_service)."""

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme Corp"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 201
    assert response.json()["proposal_name"] == "Acme Corp - Website Revamp Proposal"


async def test_auto_naming_uses_the_configured_template(client, member, factory):
    await factory.organization_settings(
        organization_name="Innoboon",
        proposal_naming_template="{organization_name} :: {client_name} :: {project_title}",
    )

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme Corp"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.json()["proposal_name"] == "Innoboon :: Acme Corp :: Website Revamp"


async def test_an_explicit_proposal_name_is_not_overwritten_by_auto_naming(client, member):
    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme Corp", "proposal_name": "My Own Title"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.json()["proposal_name"] == "My Own Title"


async def test_upload_requirement_document_attaches_to_an_existing_proposal(
    client, member, factory, db
):
    proposal = await factory.proposal(user=member, title="Existing", client_name="Original Client")

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Different Client", "proposal_id": str(proposal.id)},
        files=[("files", upload("extra.pdf"))],
    )

    assert response.status_code == 201
    assert response.json()["proposal_id"] == proposal.id
    # client_name/proposal_name are only extraction context for the new files;
    # the existing proposal keeps its own values.
    assert response.json()["client_name"] == "Original Client"
    await db.refresh(proposal)
    assert proposal.title == "Existing"
    assert proposal.client_name == "Original Client"


async def test_upload_requirement_document_404s_for_an_unknown_proposal(client, member_headers):
    response = await client.post(
        "/proposal/requirement-documents",
        headers=member_headers,
        data={"client_name": "Acme", "proposal_id": "999999"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Proposal not found"


async def test_upload_requirement_document_404s_for_a_soft_deleted_proposal(client, member, factory):
    proposal = await factory.proposal(user=member, is_active=False)

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme", "proposal_id": str(proposal.id)},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 404


async def test_upload_requirement_document_requires_at_least_one_file(client, member_headers):
    response = await client.post(
        "/proposal/requirement-documents", headers=member_headers, data={"client_name": "Acme"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "At least one file is required."


async def test_upload_requirement_document_ignores_blank_filename_parts(
    client, member_headers, fake_s3
):
    """Swagger sends an untouched file input as a part with a blank filename; it
    must not be stored as a 0-byte object."""

    response = await client.post(
        "/proposal/requirement-documents",
        headers=member_headers,
        data={"client_name": "Acme"},
        files=[("files", (" ", b"", "application/octet-stream"))],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "At least one file is required."
    assert fake_s3.uploaded == []


async def test_upload_requirement_document_rejects_a_non_file_files_field(
    client, member_headers, fake_s3
):
    """A completely empty part carries no filename at all, so it arrives as a
    plain form value — rejected by request validation before the handler runs."""

    response = await client.post(
        "/proposal/requirement-documents",
        headers=member_headers,
        data={"client_name": "Acme", "files": ""},
    )

    assert response.status_code == 422
    assert fake_s3.uploaded == []


async def test_upload_requirement_document_requires_client_name(client, member_headers):
    response = await client.post(
        "/proposal/requirement-documents", headers=member_headers, files=[("files", upload("rfp.pdf"))]
    )

    assert response.status_code == 422


async def test_upload_requirement_document_502s_when_s3_fails(client, member, fake_s3):
    fake_s3.upload_error = RuntimeError("bucket unreachable")

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to upload file to storage. Please try again."


async def test_upload_requirement_document_422s_when_parsing_fails(client, member, monkeypatch):
    """A failed extraction/parse is reported as 422, not swallowed into a
    success response with an empty summary."""

    import router.proposals as proposals_router

    async def failing_pipeline(db, document, additional_context=None):
        document.status = DocumentStatus.FAILED
        await db.commit()
        await db.refresh(document)
        return document

    monkeypatch.setattr(proposals_router, "process_requirement_document_pipeline", failing_pipeline)

    response = await client.post(
        "/proposal/requirement-documents",
        headers=auth_headers(member),
        data={"client_name": "Acme"},
        files=[("files", upload("rfp.pdf"))],
    )

    assert response.status_code == 422
    assert "Failed to process requirement document" in response.json()["detail"]


async def test_upload_requirement_document_requires_a_token(client):
    response = await client.post(
        "/proposal/requirement-documents",
        data={"client_name": "Acme"},
        files=[("files", upload("rfp.pdf"))],
    )
    assert response.status_code == 401


# ------------------------------------------------------------------
# POST /proposal/generate  (SSE)
# ------------------------------------------------------------------

@pytest.fixture
def stub_generation(monkeypatch):
    """Replaces the LangGraph pipeline with a fixed SSE script."""

    import router.proposals as proposals_router

    calls = []

    async def fake_stream(proposal_id: int, page_count: int, generation_mode):
        calls.append({"proposal_id": proposal_id, "page_count": page_count, "mode": generation_mode})
        yield 'event: section_start\ndata: {"name": "Executive Summary"}\n\n'
        yield 'event: section_chunk\ndata: {"content": "Hello"}\n\n'
        yield 'event: section_done\ndata: {"name": "Executive Summary"}\n\n'
        yield "event: done\ndata: {}\n\n"

    monkeypatch.setattr(proposals_router, "generate_proposal_stream", fake_stream)
    return calls


async def test_generate_streams_server_sent_events(client, member, factory, stub_generation):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        "/proposal/generate",
        headers=auth_headers(member),
        json={
            "proposal_id": proposal.id,
            "page_count": MIN_PROPOSAL_PAGES,
            "generation_mode": GenerationMode.LLM_ONLY.value,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: section_start" in response.text
    assert "event: done" in response.text
    assert stub_generation == [
        {
            "proposal_id": proposal.id,
            "page_count": MIN_PROPOSAL_PAGES,
            "mode": GenerationMode.LLM_ONLY,
        }
    ]


async def test_generate_404s_for_an_unknown_proposal(client, member_headers, stub_generation):
    response = await client.post(
        "/proposal/generate",
        headers=member_headers,
        json={
            "proposal_id": 999999,
            "page_count": MIN_PROPOSAL_PAGES,
            "generation_mode": GenerationMode.LLM_ONLY.value,
        },
    )

    assert response.status_code == 404
    assert stub_generation == []  # validated before any work starts


async def test_generate_404s_for_a_soft_deleted_proposal(client, member, factory, stub_generation):
    proposal = await factory.proposal(user=member, is_active=False)

    response = await client.post(
        "/proposal/generate",
        headers=auth_headers(member),
        json={
            "proposal_id": proposal.id,
            "page_count": MIN_PROPOSAL_PAGES,
            "generation_mode": GenerationMode.LLM_ONLY.value,
        },
    )

    assert response.status_code == 404


@pytest.mark.parametrize("page_count", [0, 1, MIN_PROPOSAL_PAGES - 1, -5])
async def test_generate_rejects_a_page_count_below_the_minimum(
    client, member, factory, stub_generation, page_count
):
    """Every section is always produced, so a shorter target cannot fit their
    required outlines — rejected up front rather than silently overrunning."""

    proposal = await factory.proposal(user=member)

    response = await client.post(
        "/proposal/generate",
        headers=auth_headers(member),
        json={
            "proposal_id": proposal.id,
            "page_count": page_count,
            "generation_mode": GenerationMode.LLM_ONLY.value,
        },
    )

    assert response.status_code == 422
    assert stub_generation == []


@pytest.mark.parametrize(
    "payload",
    [
        {"page_count": 10, "generation_mode": "llm_only"},
        {"proposal_id": 1, "generation_mode": "llm_only"},
        {"proposal_id": 1, "page_count": 10},
        {"proposal_id": 1, "page_count": 10, "generation_mode": "telepathy"},
        {"proposal_id": "abc", "page_count": 10, "generation_mode": "llm_only"},
    ],
    ids=["no-id", "no-page-count", "no-mode", "bad-mode", "bad-id-type"],
)
async def test_generate_validation_errors(client, member_headers, stub_generation, payload):
    response = await client.post("/proposal/generate", headers=member_headers, json=payload)
    assert response.status_code == 422


async def test_generate_accepts_knowledge_augmented_mode(client, member, factory, stub_generation):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        "/proposal/generate",
        headers=auth_headers(member),
        json={
            "proposal_id": proposal.id,
            "page_count": 12,
            "generation_mode": GenerationMode.KNOWLEDGE_AUGMENTED.value,
        },
    )

    assert response.status_code == 200
    assert stub_generation[0]["mode"] == GenerationMode.KNOWLEDGE_AUGMENTED


async def test_generate_requires_a_token(client, factory, member):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        "/proposal/generate",
        json={
            "proposal_id": proposal.id,
            "page_count": MIN_PROPOSAL_PAGES,
            "generation_mode": "llm_only",
        },
    )

    assert response.status_code == 401


# ------------------------------------------------------------------
# GET /proposal/templates
# ------------------------------------------------------------------

async def test_list_export_templates(client, member_headers):
    from constants import EXPORT_TEMPLATES

    response = await client.get("/proposal/templates", headers=member_headers)

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [template["id"] for template in EXPORT_TEMPLATES]
    assert all(row["preview_url"].startswith("https://s3.test/") for row in body)


async def test_the_templates_route_is_not_swallowed_by_the_dynamic_path(client, member_headers):
    """/proposal/templates is declared before /{proposal_id}; if that order ever
    flips, "templates" is parsed as an id."""

    response = await client.get("/proposal/templates", headers=member_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


async def test_list_export_templates_requires_a_token(client):
    response = await client.get("/proposal/templates")
    assert response.status_code == 401


# ------------------------------------------------------------------
# GET /proposal/stats
# ------------------------------------------------------------------

async def test_stats_reports_zero_for_every_status_when_empty(client, member_headers):
    response = await client.get("/proposal/stats", headers=member_headers)

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "inprogress": 0,
        "generating": 0,
        "review": 0,
        "done": 0,
        "failed": 0,
    }


async def test_stats_breaks_down_by_status(client, member, factory):
    await factory.proposal(user=member, status=ProposalStatus.INPROGRESS)
    await factory.proposal(user=member, status=ProposalStatus.INPROGRESS)
    await factory.proposal(user=member, status=ProposalStatus.DONE)
    await factory.proposal(user=member, status=ProposalStatus.FAILED)

    response = await client.get("/proposal/stats", headers=auth_headers(member))

    assert response.json() == {
        "total": 4,
        "inprogress": 2,
        "generating": 0,
        "review": 0,
        "done": 1,
        "failed": 1,
    }


async def test_stats_ignores_soft_deleted_proposals(client, member, factory):
    await factory.proposal(user=member, status=ProposalStatus.DONE)
    await factory.proposal(user=member, status=ProposalStatus.DONE, is_active=False)

    response = await client.get("/proposal/stats", headers=auth_headers(member))

    assert response.json()["done"] == 1
    assert response.json()["total"] == 1


# ------------------------------------------------------------------
# GET /proposal
# ------------------------------------------------------------------

async def test_list_proposals_newest_first_with_pagination(client, member, factory):
    for index in range(3):
        await factory.proposal(user=member, title=f"Proposal {index}")

    response = await client.get("/proposal?page=1&limit=2", headers=auth_headers(member))

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["total_pages"] == 2
    assert len(body["data"]) == 2


async def test_list_proposals_includes_sections_and_document_ids(client, member, factory):
    proposal = await factory.proposal(user=member)
    await factory.requirement_document(user=member, proposal=proposal)
    await factory.section(proposal=proposal, title="Executive Summary", order_index=0)

    response = await client.get("/proposal", headers=auth_headers(member))

    row = response.json()["data"][0]
    assert len(row["requirement_document_ids"]) == 1
    assert [section["title"] for section in row["sections"]] == ["Executive Summary"]


async def test_list_proposals_searches_title_and_client_name(client, member, factory):
    await factory.proposal(user=member, title="Cloud Migration", client_name="Acme")
    await factory.proposal(user=member, title="Website Build", client_name="Globex Cloud")
    await factory.proposal(user=member, title="Security Audit", client_name="Initech")

    response = await client.get("/proposal?search=cloud", headers=auth_headers(member))

    titles = {row["title"] for row in response.json()["data"]}
    assert titles == {"Cloud Migration", "Website Build"}


async def test_list_proposals_filters_by_status(client, member, factory):
    await factory.proposal(user=member, title="Draft", status=ProposalStatus.INPROGRESS)
    await factory.proposal(user=member, title="Finished", status=ProposalStatus.DONE)

    response = await client.get("/proposal?status=done", headers=auth_headers(member))

    assert [row["title"] for row in response.json()["data"]] == ["Finished"]


async def test_list_proposals_filters_by_creator(client, member, factory):
    other = await factory.user(email="other-author@example.com")
    await factory.proposal(user=member, title="Mine")
    await factory.proposal(user=other, title="Theirs")

    response = await client.get(
        f"/proposal?created_by={member.id}", headers=auth_headers(member)
    )

    assert [row["title"] for row in response.json()["data"]] == ["Mine"]


async def test_list_proposals_filters_by_creation_date(client, member, factory):
    from datetime import datetime

    await factory.proposal(user=member, title="Old", created_at=datetime(2024, 1, 1, 12, 0))
    await factory.proposal(user=member, title="New", created_at=datetime(2026, 1, 1, 12, 0))

    from_only = await client.get(
        "/proposal?created_from=2025-01-01T00:00:00", headers=auth_headers(member)
    )
    to_only = await client.get(
        "/proposal?created_to=2025-01-01T00:00:00", headers=auth_headers(member)
    )

    assert [row["title"] for row in from_only.json()["data"]] == ["New"]
    assert [row["title"] for row in to_only.json()["data"]] == ["Old"]


async def test_list_proposals_excludes_soft_deleted(client, member, factory):
    await factory.proposal(user=member, title="Live")
    await factory.proposal(user=member, title="Deleted", is_active=False)

    response = await client.get("/proposal", headers=auth_headers(member))

    assert [row["title"] for row in response.json()["data"]] == ["Live"]


async def test_list_proposals_is_empty_rather_than_404(client, member_headers):
    response = await client.get("/proposal", headers=member_headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


async def test_list_proposals_rejects_an_unknown_status(client, member_headers):
    response = await client.get("/proposal?status=archived", headers=member_headers)
    assert response.status_code == 422


async def test_list_proposals_requires_a_token(client):
    response = await client.get("/proposal")
    assert response.status_code == 401


# ------------------------------------------------------------------
# PATCH /proposal/{id}/status
# ------------------------------------------------------------------

@pytest.mark.parametrize(
    "current, target",
    [
        (ProposalStatus.INPROGRESS, ProposalStatus.GENERATING),
        (ProposalStatus.GENERATING, ProposalStatus.REVIEW),
        (ProposalStatus.REVIEW, ProposalStatus.DONE),
        (ProposalStatus.INPROGRESS, ProposalStatus.DONE),
    ],
)
async def test_status_can_move_forward(client, member, factory, db, current, target):
    proposal = await factory.proposal(user=member, status=current)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status={target.value}", headers=auth_headers(member)
    )

    assert response.status_code == 200
    assert response.json()["status"] == target.value
    await db.refresh(proposal)
    assert proposal.status == target


@pytest.mark.parametrize(
    "current, target",
    [
        (ProposalStatus.GENERATING, ProposalStatus.INPROGRESS),
        (ProposalStatus.REVIEW, ProposalStatus.GENERATING),
        (ProposalStatus.DONE, ProposalStatus.REVIEW),
        (ProposalStatus.DONE, ProposalStatus.INPROGRESS),
    ],
)
async def test_status_cannot_move_backward(client, member, factory, current, target):
    """A stale client call must not undo progress the pipeline already made."""

    proposal = await factory.proposal(user=member, status=current)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status={target.value}", headers=auth_headers(member)
    )

    assert response.status_code == 409
    assert "Cannot move proposal status backward" in response.json()["detail"]


async def test_status_can_stay_the_same(client, member, factory):
    proposal = await factory.proposal(user=member, status=ProposalStatus.REVIEW)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status=review", headers=auth_headers(member)
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "current",
    [ProposalStatus.INPROGRESS, ProposalStatus.GENERATING, ProposalStatus.REVIEW, ProposalStatus.DONE],
)
async def test_failed_can_always_be_set(client, member, factory, current):
    """FAILED is an abort marker, not a pipeline stage, so it is exempt from the
    forward-only rule."""

    proposal = await factory.proposal(user=member, status=current)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status=failed", headers=auth_headers(member)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"


@pytest.mark.parametrize(
    "target",
    [ProposalStatus.INPROGRESS, ProposalStatus.GENERATING, ProposalStatus.REVIEW, ProposalStatus.DONE],
)
async def test_a_failed_proposal_can_be_moved_anywhere(client, member, factory, target):
    """Recovering from FAILED must be possible — otherwise a failed proposal is
    permanently stuck."""

    proposal = await factory.proposal(user=member, status=ProposalStatus.FAILED)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status={target.value}", headers=auth_headers(member)
    )

    assert response.status_code == 200
    assert response.json()["status"] == target.value


async def test_marking_done_schedules_knowledge_reingestion(
    client, member, factory, stub_background_pipelines
):
    proposal = await factory.proposal(user=member, status=ProposalStatus.REVIEW)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status=done", headers=auth_headers(member)
    )

    assert response.status_code == 200
    assert stub_background_pipelines["ingest_proposal_as_knowledge"] == [proposal.id]


async def test_marking_done_again_reindexes_the_latest_content(
    client, member, factory, stub_background_pipelines
):
    """Deliberate: every done call re-ingests, so edits made after the first
    approval still reach the knowledge base."""

    proposal = await factory.proposal(user=member, status=ProposalStatus.DONE)

    await client.patch(f"/proposal/{proposal.id}/status?status=done", headers=auth_headers(member))
    await client.patch(f"/proposal/{proposal.id}/status?status=done", headers=auth_headers(member))

    assert stub_background_pipelines["ingest_proposal_as_knowledge"] == [proposal.id, proposal.id]


async def test_moving_to_a_non_done_status_does_not_reingest(
    client, member, factory, stub_background_pipelines
):
    proposal = await factory.proposal(user=member, status=ProposalStatus.INPROGRESS)

    await client.patch(f"/proposal/{proposal.id}/status?status=review", headers=auth_headers(member))

    assert stub_background_pipelines["ingest_proposal_as_knowledge"] == []


async def test_set_status_404s_for_an_unknown_proposal(client, member_headers):
    response = await client.patch("/proposal/999999/status?status=done", headers=member_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Proposal not found"


async def test_set_status_requires_the_status_parameter(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.patch(f"/proposal/{proposal.id}/status", headers=auth_headers(member))

    assert response.status_code == 422


async def test_set_status_rejects_an_unknown_status(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.patch(
        f"/proposal/{proposal.id}/status?status=archived", headers=auth_headers(member)
    )

    assert response.status_code == 422


async def test_set_status_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.patch(f"/proposal/{proposal.id}/status?status=done")

    assert response.status_code == 401


# ------------------------------------------------------------------
# DELETE /proposal/{id}
# ------------------------------------------------------------------

async def test_delete_proposal_soft_deletes_it(client, member, factory, db):
    proposal = await factory.proposal(user=member)

    response = await client.delete(f"/proposal/{proposal.id}", headers=auth_headers(member))

    assert response.status_code == 204
    assert await get_proposal_by_id(db, proposal.id) is None

    listing = await client.get("/proposal", headers=auth_headers(member))
    assert listing.json()["data"] == []


async def test_delete_proposal_leaves_sections_and_documents_intact(client, member, factory, db):
    """Matches how deleting a knowledge document does not cascade to its chunks."""

    proposal = await factory.proposal(user=member)
    section = await factory.section(proposal=proposal)
    document = await factory.requirement_document(user=member, proposal=proposal)

    await client.delete(f"/proposal/{proposal.id}", headers=auth_headers(member))

    await db.refresh(section)
    await db.refresh(document)
    assert section.is_active is True
    assert document.is_active is True


async def test_delete_proposal_404s_for_an_unknown_id(client, member_headers):
    response = await client.delete("/proposal/999999", headers=member_headers)
    assert response.status_code == 404


async def test_delete_proposal_is_not_repeatable(client, member, factory):
    proposal = await factory.proposal(user=member)

    first = await client.delete(f"/proposal/{proposal.id}", headers=auth_headers(member))
    second = await client.delete(f"/proposal/{proposal.id}", headers=auth_headers(member))

    assert first.status_code == 204
    assert second.status_code == 404


async def test_delete_proposal_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)
    response = await client.delete(f"/proposal/{proposal.id}")
    assert response.status_code == 401


# ------------------------------------------------------------------
# POST /proposal/{id}/export
# ------------------------------------------------------------------

async def test_export_pdf_returns_a_download(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member, title="Acme Proposal")
    await factory.section(proposal=proposal, title="Intro", order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export",
        headers=auth_headers(member),
        json={"template_id": 1, "format": "pdf"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="acme_proposal.pdf"'
    assert response.content == b"%PDF-1.7 fake"


async def test_export_docx_returns_a_download(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member, title="Acme Proposal")
    await factory.section(proposal=proposal, title="Intro", order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export",
        headers=auth_headers(member),
        json={"format": "docx"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.content == b"PK\x03\x04 fake-docx"


async def test_export_marks_the_proposal_done(client, member, factory, db, stub_renderers):
    proposal = await factory.proposal(user=member, status=ProposalStatus.REVIEW)
    await factory.section(proposal=proposal, order_index=0)

    await client.post(
        f"/proposal/{proposal.id}/export",
        headers=auth_headers(member),
        json={"format": "pdf"},
    )

    await db.refresh(proposal)
    assert proposal.status == ProposalStatus.DONE


async def test_export_409s_when_there_are_no_sections(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={"format": "pdf"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Proposal has no generated sections to export"


async def test_export_404s_for_an_unknown_template(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export",
        headers=auth_headers(member),
        json={"template_id": 99, "format": "pdf"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Template not found"


async def test_export_404s_for_an_unknown_proposal(client, member_headers, stub_renderers):
    response = await client.post(
        "/proposal/999999/export", headers=member_headers, json={"format": "pdf"}
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Proposal not found"


async def test_export_502s_when_rendering_blows_up(
    client, member, factory, stub_renderers, monkeypatch
):
    """`stub_renderers` first, then override just the PDF step — otherwise the
    live Markdown->HTML step fails first and the 502 guard is never reached."""

    import services.proposal_export_service as export_service

    def explode(html):
        raise RuntimeError("weasyprint failed")

    monkeypatch.setattr(export_service, "render_pdf_from_html", explode)
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={"format": "pdf"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to render proposal export"


async def test_export_500s_when_markdown_to_html_conversion_fails(client, member, factory, monkeypatch):
    """Current behaviour, pinned deliberately.

    `render_proposal_html` runs every section's Markdown through `pypandoc`, so
    the export depends on the external pandoc binary even for a PDF — but that
    call sits *outside* the try/except that produces the friendly 502, so a
    missing or failing pandoc surfaces as an opaque 500. See the xfail below.
    """

    import services.proposal_export_service as export_service

    def explode(*args, **kwargs):
        raise OSError("No pandoc was found")

    monkeypatch.setattr(export_service, "render_proposal_html", explode)
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={"format": "pdf"}
    )

    assert response.status_code == 500


@pytest.mark.xfail(
    strict=True,
    reason=(
        "GAP: services/proposal_export_service.render_proposal_document only wraps the "
        "PDF/DOCX step in try/except -> 502. The Markdown->HTML step before it "
        "(rendering/html_renderer._section_to_html -> pypandoc) also needs the native "
        "pandoc binary, so an unavailable pandoc returns an opaque 500 instead of the "
        "'Failed to render proposal export' 502. Move render_proposal_html inside the guard."
    ),
)
async def test_export_should_502_when_markdown_to_html_conversion_fails(client, member, factory, monkeypatch):
    import services.proposal_export_service as export_service

    def explode(*args, **kwargs):
        raise OSError("No pandoc was found")

    monkeypatch.setattr(export_service, "render_proposal_html", explode)
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={"format": "pdf"}
    )

    assert response.status_code == 502


async def test_export_rejects_an_unknown_format(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={"format": "xlsx"}
    )

    assert response.status_code == 422


async def test_export_requires_a_format(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        f"/proposal/{proposal.id}/export", headers=auth_headers(member), json={}
    )

    assert response.status_code == 422


async def test_export_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)
    response = await client.post(f"/proposal/{proposal.id}/export", json={"format": "pdf"})
    assert response.status_code == 401


# ------------------------------------------------------------------
# POST /proposal/{id}/export/email
# ------------------------------------------------------------------

async def test_email_export_sends_the_file_and_confirms(
    client, member, factory, stub_renderers, sent_emails
):
    proposal = await factory.proposal(user=member, title="Acme Proposal")
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        headers=auth_headers(member),
        json={"format": "pdf", "email": "client@example.com"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "proposal_id": proposal.id,
        "template_id": 1,
        "format": "pdf",
        "sent_to": "client@example.com",
    }
    assert [email.kind for email in sent_emails] == ["export"]


async def test_email_export_does_not_return_the_binary(
    client, member, factory, stub_renderers, sent_emails
):
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        headers=auth_headers(member),
        json={"format": "pdf", "email": "client@example.com"},
    )

    assert response.headers["content-type"].startswith("application/json")
    assert b"%PDF" not in response.content


async def test_email_export_502s_when_sending_fails(
    client, member, factory, stub_renderers, monkeypatch
):
    import services.proposal_export_service as export_service

    async def explode(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(export_service, "send_proposal_export_email", explode)
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        headers=auth_headers(member),
        json={"format": "pdf", "email": "client@example.com"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to send proposal export email"


async def test_email_export_rejects_an_invalid_address(client, member, factory, stub_renderers):
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        headers=auth_headers(member),
        json={"format": "pdf", "email": "not-an-email"},
    )

    assert response.status_code == 422


async def test_email_export_409s_when_there_is_nothing_to_export(
    client, member, factory, stub_renderers, sent_emails
):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        headers=auth_headers(member),
        json={"format": "pdf", "email": "client@example.com"},
    )

    assert response.status_code == 409
    assert sent_emails == []


async def test_email_export_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.post(
        f"/proposal/{proposal.id}/export/email",
        json={"format": "pdf", "email": "client@example.com"},
    )

    assert response.status_code == 401
