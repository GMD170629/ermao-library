from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_grouping_http_surface_has_no_identity_aliases(client: TestClient) -> None:
    paths = create_app().openapi()["paths"]
    assert "/api/books" in paths
    assert "/api/books/{book_id}" in paths
    assert "/api/library/groupings" not in paths
    assert not any(
        path.startswith("/api/works")
        or path.startswith("/api/versions")
        or path.startswith("/api/volumes")
        for path in paths
    )
    assert client.get("/api/library/groupings").status_code == 404


def test_grouping_filter_parameter_pairs_are_not_accepted_by_book_route(
    client: TestClient,
) -> None:
    response = client.get("/api/books", params={"facetKind": "AUTHOR"})
    assert response.status_code == 401
