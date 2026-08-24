from __future__ import annotations

import pytest

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User

BODY_OPERATIONS = (
    ("POST", "/api/books/import"),
    ("PATCH", "/api/books/book-id"),
    ("PATCH", "/api/books/book-id/resources/resource-id"),
    ("DELETE", "/api/books/book-id/resources/resource-id/source"),
    ("POST", "/api/shelves"),
    ("PATCH", "/api/shelves/shelf-id"),
)


def test_library_and_shelf_write_bodies_are_documented() -> None:
    schema = create_app().openapi()
    templated_operations = (
        ("post", "/api/books/import"),
        ("patch", "/api/books/{book_id}"),
        ("patch", "/api/books/{book_id}/resources/{resource_id}"),
        ("delete", "/api/books/{book_id}/resources/{resource_id}/source"),
        ("post", "/api/shelves"),
        ("patch", "/api/shelves/{shelf_id}"),
    )

    for method, path in templated_operations:
        assert "requestBody" in schema["paths"][path][method], (method, path)

    assert "201" in schema["paths"]["/api/shelves"]["post"]["responses"]
    assert (
        "206"
        in schema["paths"]["/api/resources/{resource_id}/asset"]["get"]["responses"]
    )
    assert (
        "206"
        in schema["paths"]["/api/resources/{resource_id}/pages/{page_index}"]["get"][
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

    expected_status = 400 if path == "/api/books/import" else 422
    assert response.status_code == expected_status, (method, path, response.text)
