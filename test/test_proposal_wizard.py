"""The generation-wizard endpoints on router/proposals.py — GET
/proposal/{proposal_id}/state plus GET/PATCH /proposal/{proposal_id}/sections.
Previously served by the separate, unprefixed router/proposal_temp.py."""

from helpers import auth_headers

from database.db_enum import DocumentStatus, GenerationMode, ProposalStatus

# ------------------------------------------------------------------
# GET /proposal/{proposal_id}/state
# ------------------------------------------------------------------


async def test_proposal_state_starts_at_proposal_details(client, member, factory):
    proposal = await factory.proposal(user=member, title="Wizard", client_name="Acme")

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    assert response.status_code == 200
    body = response.json()
    assert body["current_step"] == "proposal_details"
    assert body["proposal_details"]["proposal_name"] == "Wizard"
    assert body["proposal_details"]["client_name"] == "Acme"
    assert body["proposal_details"]["files"] == []
    assert body["summary"] is None
    assert body["generation_config"] is None
    assert body["generation"] is None


async def test_proposal_state_moves_to_summary_once_a_file_is_parsed(client, member, factory):
    proposal = await factory.proposal(user=member)
    await factory.requirement_document(user=member, proposal=proposal, summary="Client needs a portal")

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    body = response.json()
    assert body["current_step"] == "generation_config"
    assert body["summary"]["summary"] == "Client needs a portal"
    assert len(body["summary"]["files"]) == 1


async def test_proposal_state_reports_summary_step_while_parsing(client, member, factory):
    """An uploaded-but-unparsed document has no summary yet, so the wizard sits
    on the summary step."""

    proposal = await factory.proposal(user=member)
    await factory.requirement_document(user=member, proposal=proposal, status=DocumentStatus.EXTRACTING, summary=None)

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    assert response.json()["current_step"] == "summary"
    assert response.json()["summary"] is None


async def test_proposal_state_reaches_generation_once_a_mode_is_set(client, member, factory):
    proposal = await factory.proposal(
        user=member,
        status=ProposalStatus.GENERATING,
        generation_mode=GenerationMode.KNOWLEDGE_AUGMENTED,
        page_count=10,
    )
    await factory.requirement_document(user=member, proposal=proposal, summary="A summary")

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    body = response.json()
    assert body["current_step"] == "generation"
    assert body["generation_config"] == {
        "generation_mode": "knowledge_augmented",
        "page_count": 10,
    }
    assert body["generation"] == {"status": "generating"}


async def test_proposal_state_collapses_review_and_done_to_done(client, member, factory):
    proposal = await factory.proposal(
        user=member,
        status=ProposalStatus.REVIEW,
        generation_mode=GenerationMode.LLM_ONLY,
        page_count=8,
    )
    await factory.requirement_document(user=member, proposal=proposal, summary="A summary")

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    assert response.json()["generation"] == {"status": "done"}


async def test_proposal_state_reports_a_failed_generation(client, member, factory):
    proposal = await factory.proposal(
        user=member,
        status=ProposalStatus.FAILED,
        generation_mode=GenerationMode.LLM_ONLY,
        page_count=8,
    )
    await factory.requirement_document(user=member, proposal=proposal, summary="A summary")

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    assert response.json()["generation"] == {"status": "failed"}


async def test_proposal_state_combines_several_files(client, member, factory):
    """Reading only the newest document used to hide every earlier upload's
    summary, matches and tags."""

    proposal = await factory.proposal(user=member)
    await factory.requirement_document(
        user=member,
        proposal=proposal,
        summary="First summary",
        capability_tags=[{"name": "Backend", "confidence": 0.4}],
        knowledge_matches=[
            {
                "document_id": 1,
                "title": "Doc A",
                "source_filename": "a.pdf",
                "breadcrumb": "A",
                "match_percent": 40,
            }
        ],
    )
    await factory.requirement_document(
        user=member,
        proposal=proposal,
        summary="Second summary",
        capability_tags=[{"name": "Backend", "confidence": 0.9}],
        knowledge_matches=[
            {
                "document_id": 1,
                "title": "Doc A",
                "source_filename": "a.pdf",
                "breadcrumb": "A",
                "match_percent": 80,
            }
        ],
    )

    response = await client.get(f"/proposal/{proposal.id}/state", headers=auth_headers(member))

    summary = response.json()["summary"]
    assert "First summary" in summary["summary"]
    assert "Second summary" in summary["summary"]
    assert len(summary["files"]) == 2
    # De-duplicated, strongest score kept per knowledge document / capability.
    assert summary["knowledge_matches"] == [
        {
            "document_id": 1,
            "title": "Doc A",
            "source_filename": "a.pdf",
            "breadcrumb": "A",
            "match_percent": 80,
        }
    ]
    assert summary["capability_tags"] == [{"name": "Backend", "confidence": 0.9}]


async def test_proposal_state_404s_for_an_unknown_proposal(client, member_headers):
    response = await client.get("/proposal/999999/state", headers=member_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Proposal not found"


async def test_proposal_state_rejects_a_non_numeric_proposal_id(client, member_headers):
    """proposal_id is a path param now, so a non-integer is a 422 from path
    validation rather than a missing-query-param error."""

    response = await client.get("/proposal/not-a-number/state", headers=member_headers)
    assert response.status_code == 422


async def test_proposal_state_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)
    response = await client.get(f"/proposal/{proposal.id}/state")
    assert response.status_code == 401


# ------------------------------------------------------------------
# GET /proposal/{proposal_id}/sections
# ------------------------------------------------------------------


async def test_get_proposal_sections_in_order(client, member, factory):
    proposal = await factory.proposal(user=member, title="Reviewable", client_name="Acme")
    await factory.section(proposal=proposal, title="Third", order_index=2)
    await factory.section(proposal=proposal, title="First", order_index=0)
    await factory.section(proposal=proposal, title="Second", order_index=1)

    response = await client.get(f"/proposal/{proposal.id}/sections", headers=auth_headers(member))

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Reviewable"
    assert body["client_name"] == "Acme"
    assert [section["title"] for section in body["sections"]] == ["First", "Second", "Third"]
    assert [section["order"] for section in body["sections"]] == [0, 1, 2]


async def test_get_proposal_sections_is_empty_for_an_ungenerated_proposal(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.get(f"/proposal/{proposal.id}/sections", headers=auth_headers(member))

    assert response.status_code == 200
    assert response.json()["sections"] == []


async def test_get_proposal_sections_404s_for_an_unknown_proposal(client, member_headers):
    response = await client.get("/proposal/999999/sections", headers=member_headers)
    assert response.status_code == 404


async def test_get_proposal_sections_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)
    response = await client.get(f"/proposal/{proposal.id}/sections")
    assert response.status_code == 401


# ------------------------------------------------------------------
# PATCH /proposal/{proposal_id}/sections
# ------------------------------------------------------------------


async def test_reorder_sections(client, member, factory):
    proposal = await factory.proposal(user=member)
    first = await factory.section(proposal=proposal, title="First", order_index=0)
    second = await factory.section(proposal=proposal, title="Second", order_index=1)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": [{"id": second.id, "order": 0}, {"id": first.id, "order": 1}]},
    )

    assert response.status_code == 200
    assert [section["title"] for section in response.json()["sections"]] == ["Second", "First"]


async def test_omitting_a_section_deletes_it(client, member, factory):
    proposal = await factory.proposal(user=member)
    keep = await factory.section(proposal=proposal, title="Keep", order_index=0)
    await factory.section(proposal=proposal, title="Drop", order_index=1)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": [{"id": keep.id, "order": 0}]},
    )

    assert response.status_code == 200
    assert [section["title"] for section in response.json()["sections"]] == ["Keep"]


async def test_an_empty_section_list_clears_every_section(client, member, factory):
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": []},
    )

    assert response.status_code == 200
    assert response.json()["sections"] == []


async def test_reorder_rejects_a_section_from_another_proposal(client, member, factory):
    proposal = await factory.proposal(user=member)
    other_proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)
    foreign = await factory.section(proposal=other_proposal, order_index=0)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": [{"id": foreign.id, "order": 0}]},
    )

    assert response.status_code == 400
    assert f"Section {foreign.id} does not belong to proposal {proposal.id}" in response.json()["detail"]


async def test_reorder_rejects_an_unknown_section_id(client, member, factory):
    proposal = await factory.proposal(user=member)
    await factory.section(proposal=proposal, order_index=0)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": [{"id": 999999, "order": 0}]},
    )

    assert response.status_code == 400


async def test_reorder_validates_nothing_before_rejecting(client, member, factory, db):
    """The ownership check runs over the whole payload before any delete, so a
    partially-valid request leaves the sections untouched."""

    proposal = await factory.proposal(user=member)
    keep = await factory.section(proposal=proposal, title="Keep", order_index=0)

    response = await client.patch(
        f"/proposal/{proposal.id}/sections",
        headers=auth_headers(member),
        json={"sections": [{"id": keep.id, "order": 5}, {"id": 999999, "order": 0}]},
    )

    assert response.status_code == 400
    await db.refresh(keep)
    assert keep.order_index == 0


async def test_reorder_404s_for_an_unknown_proposal(client, member_headers):
    response = await client.patch("/proposal/999999/sections", headers=member_headers, json={"sections": []})
    assert response.status_code == 404


async def test_reorder_requires_the_sections_key(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.patch(f"/proposal/{proposal.id}/sections", headers=auth_headers(member), json={})

    assert response.status_code == 422


async def test_reorder_requires_a_token(client, member, factory):
    proposal = await factory.proposal(user=member)

    response = await client.patch(f"/proposal/{proposal.id}/sections", json={"sections": []})

    assert response.status_code == 401
