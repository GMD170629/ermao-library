from __future__ import annotations

from pathlib import Path

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User


def test_structural_book_mutations_are_absent_from_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/api/works/{work_id}" not in paths
    assert "/api/books/{book_id}/resources/{resource_id}/move" not in paths
    assert "/api/books/{book_id}/resources/{resource_id}/split" not in paths
    assert "delete" not in paths["/api/books/{book_id}"]
    assert "delete" not in paths["/api/books/{book_id}/resources/{resource_id}"]


def test_structural_resource_implementations_are_removed() -> None:
    infrastructure = (
        Path(__file__).parents[3]
        / "app"
        / "modules"
        / "library"
        / "infrastructure"
    )

    assert not (infrastructure / "structural_operations.py").exists()
    assert not any(infrastructure.glob("batch_*_commands.py"))


def test_resource_metadata_contract_excludes_directory_owned_fields() -> None:
    schema = create_app().openapi()
    components = schema["components"]["schemas"]
    properties = components["UpdateResourceRequest"]["properties"]

    assert "sortOrder" not in properties
    assert "hidden" not in properties
    batch_schema = schema["paths"]["/api/books/{book_id}/resources/batch"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert batch_schema == {
        "$ref": "#/components/schemas/ResourceBatchRequest"
    }


def test_bulk_delete_is_rejected_as_directory_topology_mutation(
    client,
    db_session,
) -> None:
    db_session.add(
        User(
            id="topology-read-only-admin",
            email="topology-read-only@example.com",
            name="Topology admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
    )
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "email": "topology-read-only@example.com",
            "password": "starshipnas",
        },
    )
    assert login.status_code == 200

    response = client.post("/api/works/bulk", json={"ids": [], "action": "delete_records"})

    assert response.status_code == 404
