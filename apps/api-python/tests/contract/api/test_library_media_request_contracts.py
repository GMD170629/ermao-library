from __future__ import annotations

import pytest

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User

BODY_OPERATIONS = (
    ("PATCH", "/api/works/work-id"),
    ("PUT", "/api/works/work-id/detail-preference"),
    ("POST", "/api/works/bulk"),
    ("POST", "/api/works/bulk/find-replace/preview"),
    ("POST", "/api/works/bulk/cover"),
    ("PATCH", "/api/library/categories/facet-id"),
    ("POST", "/api/library/categories/merge"),
    ("POST", "/api/library/duplicates/merge"),
    ("POST", "/api/works/work-id/metadata/search"),
    ("POST", "/api/shelves"),
    ("PATCH", "/api/shelves/shelf-id"),
)


def test_library_and_shelf_write_bodies_are_documented() -> None:
    schema = create_app().openapi()
    templated_operations = (
        ("patch", "/api/works/{work_id}"),
        ("put", "/api/works/{work_id}/detail-preference"),
        ("post", "/api/works/bulk"),
        ("post", "/api/works/bulk/find-replace/preview"),
        ("post", "/api/works/bulk/cover"),
        ("patch", "/api/library/categories/{facet_id}"),
        ("post", "/api/library/categories/merge"),
        ("post", "/api/library/duplicates/merge"),
        ("post", "/api/works/{work_id}/metadata/search"),
        ("post", "/api/shelves"),
        ("patch", "/api/shelves/{shelf_id}"),
    )

    for method, path in templated_operations:
        assert "requestBody" in schema["paths"][path][method], (method, path)

    assert "201" in schema["paths"]["/api/shelves"]["post"]["responses"]
    assert "206" in schema["paths"]["/api/files/{file_id}"]["get"]["responses"]
    assert (
        "206"
        in schema["paths"]["/api/volumes/{volume_id}/pages/{page_index}"]["get"][
            "responses"
        ]
    )


@pytest.mark.parametrize(("method", "path"), BODY_OPERATIONS)
def test_missing_request_body_is_a_validation_error(
    client,
    db_session,
    method: str,
    path: str,
) -> None:
    db_session.add(
        User(
            id="request-contract-admin",
            email="request-contract@example.com",
            name="Request contract admin",
            password_hash=hash_password("starshipnas"),
            role="admin",
        )
    )
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={
            "email": "request-contract@example.com",
            "password": "starshipnas",
        },
    )
    assert login.status_code == 200

    response = client.request(method, path)

    assert response.status_code == 422, (method, path, response.text)
