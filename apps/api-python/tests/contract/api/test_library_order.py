"""The global manual library order is complete, unique, and persisted."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Library


def _setup_admin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/setup",
        json={
            "name": "Library owner",
            "email": "library-order@example.com",
            "password": "library-order-password",
        },
    )
    assert response.status_code == 201


def _create_library(client: TestClient, root: Path, *, name: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/libraries",
        json={
            "name": name,
            "rootPath": str(root),
            "organizationMode": "FLAT",
        },
    )
    assert response.status_code == 201
    return response.json()["data"]["library"]["id"]


def _library_ids(client: TestClient) -> list[str]:
    response = client.get("/api/libraries")
    assert response.status_code == 200
    return [library["id"] for library in response.json()["data"]["libraries"]]


def test_reorder_libraries_persists_the_requested_order(
    client: TestClient, tmp_path: Path, db_session: Session
) -> None:
    _setup_admin(client)
    first = _create_library(client, tmp_path / "first", name="First")
    second = _create_library(client, tmp_path / "second", name="Second")
    third = _create_library(client, tmp_path / "third", name="Third")

    initial = _library_ids(client)
    assert {first, second, third} <= set(initial)

    reordered = list(reversed(initial))
    response = client.put("/api/libraries/order", json={"libraryIds": reordered})

    assert response.status_code == 200
    assert [library["id"] for library in response.json()["data"]["libraries"]] == reordered
    assert _library_ids(client) == reordered

    schema_response = client.get("/api/library/filter-schema")
    assert schema_response.status_code == 200
    library_field = next(
        field
        for field in schema_response.json()["data"]["fields"]
        if field["key"] == "library"
    )
    assert [option["value"] for option in library_field["options"]] == reordered

    sort_orders = dict(
        db_session.execute(select(Library.id, Library.sort_order)).all()
    )
    assert [sort_orders[library_id] for library_id in reordered] == list(
        range(1, len(reordered) + 1)
    )


def test_reorder_libraries_rejects_incomplete_duplicate_or_unknown_ids(
    client: TestClient, tmp_path: Path
) -> None:
    _setup_admin(client)
    first = _create_library(client, tmp_path / "first", name="First")
    _create_library(client, tmp_path / "second", name="Second")
    before = _library_ids(client)

    incomplete = client.put("/api/libraries/order", json={"libraryIds": [first]})
    assert incomplete.status_code == 400
    assert incomplete.json()["error"]["code"] == "LIBRARY_ORDER_INVALID"

    duplicate = client.put(
        "/api/libraries/order", json={"libraryIds": [first, first]}
    )
    assert duplicate.status_code == 400
    assert duplicate.json()["error"]["code"] == "LIBRARY_ORDER_INVALID"

    unknown = client.put(
        "/api/libraries/order", json={"libraryIds": [first, "missing-library"]}
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "LIBRARY_ORDER_INVALID"

    empty = client.put("/api/libraries/order", json={"libraryIds": []})
    assert empty.status_code == 422

    assert _library_ids(client) == before


def test_reorder_libraries_requires_an_authenticated_session(client: TestClient) -> None:
    response = client.put("/api/libraries/order", json={"libraryIds": ["library-id"]})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
