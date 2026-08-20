from __future__ import annotations

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User


def test_structural_library_mutations_are_absent_from_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "delete" not in paths["/api/works/{work_id}"]
    assert "/api/works/{work_id}/volumes/{volume_id}/move" not in paths
    assert "/api/works/{work_id}/volumes/{volume_id}/split" not in paths
    assert "delete" not in paths["/api/works/{work_id}/volumes/{volume_id}"]


def test_volume_metadata_contract_excludes_directory_owned_fields() -> None:
    schema = create_app().openapi()
    components = schema["components"]["schemas"]
    properties = components["UpdateVolumeRequest"]["properties"]

    assert "title" not in properties
    assert "volumeIndex" not in properties
    assert "sortOrder" not in properties
    assert "hidden" not in properties
    batch_schema = schema["paths"]["/api/works/{work_id}/volumes/batch"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert batch_schema == {
        "$ref": "#/components/schemas/BatchSetMediaKindRequest"
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

    response = client.post(
        "/api/works/bulk",
        json={"ids": [], "action": "delete_records"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "LIBRARY_TOPOLOGY_READ_ONLY"
