"""Cross-cutting app behaviour: the global error handler, CORS, and routing."""

import pytest
from helpers import auth_headers
from sqlalchemy.exc import OperationalError


async def test_root_endpoint_needs_no_auth(client):
    response = await client.get("/")
    assert response.status_code == 200


async def test_unknown_path_404s(client):
    response = await client.get("/does-not-exist")
    assert response.status_code == 404


async def test_wrong_method_405s(client):
    response = await client.delete("/")
    assert response.status_code == 405


async def test_unexpected_exceptions_become_a_clean_500(client, member, factory, monkeypatch):
    """No raw traceback reaches the caller."""

    import router.category as category_router

    def explode(*args, **kwargs):
        raise RuntimeError("something broke deep inside")

    monkeypatch.setattr(category_router, "get_category_by_id", explode)

    response = await client.delete("/category/1", headers=auth_headers(member))

    assert response.status_code == 500
    assert response.json() == {"detail": "An unexpected error occurred."}
    assert "Traceback" not in response.text
    assert "something broke deep inside" not in response.text


async def test_database_errors_become_a_503(client, member, factory, monkeypatch):
    import router.category as category_router

    async def explode(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    monkeypatch.setattr(category_router, "get_category_by_id", explode)

    response = await client.delete("/category/1", headers=auth_headers(member))

    assert response.status_code == 503
    assert response.json() == {"detail": "A database error occurred. Please try again."}


async def test_http_exceptions_keep_their_status_and_detail(client, member_headers):
    """The error handler must not flatten deliberate HTTPExceptions into 500s."""

    response = await client.delete("/category/999999", headers=member_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Category not found"


async def test_cors_preflight_is_allowed(client):
    response = await client.options(
        "/category/list",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "GET" in response.headers["access-control-allow-methods"]


async def test_cors_headers_are_present_on_a_normal_response(client):
    response = await client.get("/", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_headers_survive_an_error_response(client, member, monkeypatch):
    """CORS is added outermost precisely so its headers still land on the JSON
    the error handler returns — otherwise the browser hides the error."""

    import router.category as category_router

    def explode(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(category_router, "get_category_by_id", explode)

    response = await client.delete("/category/1", headers={**auth_headers(member), "Origin": "http://localhost:3000"})

    assert response.status_code == 500
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize(
    "path",
    ["/document/list", "/proposal/templates", "/proposal/stats"],
)
async def test_static_paths_are_not_captured_by_sibling_dynamic_routes(client, member_headers, path):
    """Each of these sits next to a /{id}-style route in the same router; if the
    declaration order is ever changed, they resolve as an id instead and 422."""

    response = await client.get(path, headers=member_headers)
    assert response.status_code == 200


async def test_openapi_schema_builds(client):
    """A response_model mismatch or duplicate operation id shows up here."""

    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "Proposal AI"
    assert "/auth/login" in schema["paths"]
