"""Sanity checks for the test harness itself: the SQLite stand-in builds the
real schema, the app is reachable, and JWT auth works end to end."""

from helpers import auth_headers


async def test_root_endpoint(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Proposal AI Backend Running"}


async def test_factory_and_auth_round_trip(client, factory):
    user = await factory.user(email="smoke@example.com")
    response = await client.get("/profile", headers=auth_headers(user))
    assert response.status_code == 200
    assert response.json()["email"] == "smoke@example.com"


async def test_postgres_only_columns_round_trip(factory, db):
    """JSONB and ARRAY columns must survive the SQLite variant swap."""

    user = await factory.user()
    category = await factory.category()
    document = await factory.knowledge_document(user=user, category=category, tags=["a", "b"])
    proposal = await factory.proposal(user=user)
    requirement = await factory.requirement_document(user=user, proposal=proposal, parsed_data={"project_title": "X"})

    await db.refresh(document)
    await db.refresh(requirement)
    assert document.tags == ["a", "b"]
    assert requirement.parsed_data == {"project_title": "X"}
