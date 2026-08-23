from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


def test_book_merge_surface_is_explicitly_retired(
    client: TestClient, db_session: Session
) -> None:
    """A fresh cutover exposes no merge bridge under either identity."""

    db_session.add(
        User(
            email="book-merge-removed@example.com",
            name="Book merge removed",
            password_hash=hash_password("starshipnas"),
            role="admin",
            can_manage_system=True,
        )
    )
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": "book-merge-removed@example.com", "password": "starshipnas"},
    )
    assert login.status_code == 200

    paths = create_app().openapi()["paths"]
    assert "/api/books/merge" not in paths
    assert "/api/books/merge/preview" not in paths
    assert "/api/library/duplicates/merge" not in paths

    assert (
        client.post("/api/books/merge", json={"bookIds": ["a", "b"]}).status_code == 405
    )
    assert (
        client.post(
            "/api/books/merge/preview", json={"bookIds": ["a", "b"]}
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/library/duplicates/merge",
            json={"targetBookId": "a", "sourceBookIds": ["b"]},
        ).status_code
        == 404
    )
