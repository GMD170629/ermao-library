from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.auth import hash_password
from app.main import create_app
from app.models.auth import User

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


def test_work_merge_http_surface_is_removed(client: TestClient, db_session: Session) -> None:
    db_session.add(
        User(
            email="work-merge-removed@example.com",
            name="Work Merge Removed",
            password_hash=hash_password("starshipnas"),
            role="admin",
            can_manage_system=True,
        )
    )
    db_session.commit()
    login = client.post(
        "/api/auth/login",
        json={"email": "work-merge-removed@example.com", "password": "starshipnas"},
    )
    assert login.status_code == 200

    schema = create_app().openapi()
    paths = schema["paths"]
    assert "/api/works/merge" not in paths
    assert "/api/works/merge/preview" not in paths
    assert "/api/library/duplicates/merge" not in paths

    merge_status = client.post("/api/works/merge", json={"workIds": ["a", "b"]}).status_code
    assert merge_status in {404, 405}
    assert (
        client.post("/api/works/merge/preview", json={"workIds": ["a", "b"]}).status_code
        == 404
    )
    assert (
        client.post(
            "/api/library/duplicates/merge",
            json={"targetWorkId": "a", "sourceWorkIds": ["b"]},
        ).status_code
        == 404
    )
