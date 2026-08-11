from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app import main as app_main
from app.core.auth import hash_password
from app.db.runner import apply_schema
from app.models.auth import User

if TYPE_CHECKING:
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session


PASSWORD = "SystemContract123!"


def _create_user(
    db_session: Session,
    *,
    email: str,
    role: str = "member",
    can_manage_system: bool = False,
) -> User:
    user = User(
        email=email,
        name=email.split("@", 1)[0],
        password_hash=hash_password(PASSWORD),
        role=role,
        can_manage_system=can_manage_system,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _login(client: TestClient, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200


def _request(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
):
    return client.request(method, path, json=body)


SYSTEM_MANAGEMENT_REQUESTS = (
    ("GET", "/api/system-settings", None),
    ("PUT", "/api/system-settings", {"settings": {"readerTheme": "dark"}}),
    ("PATCH", "/api/system-settings", {"settings": {"readerTheme": "dark"}}),
    ("GET", "/api/management/events", None),
    ("DELETE", "/api/management/events", None),
    ("GET", "/api/backups", None),
    ("GET", "/api/backups/missing", None),
    ("POST", "/api/backups", None),
    ("POST", "/api/backups/missing/restore", None),
    ("DELETE", "/api/backups/missing", None),
    ("GET", "/api/backups/missing/download", None),
)


@pytest.mark.parametrize(("method", "path", "body"), SYSTEM_MANAGEMENT_REQUESTS)
def test_system_management_endpoints_reject_ordinary_members_with_stable_code(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    monkeypatch.setattr(app_main, "_requires_system_manager", lambda *_args: False)
    member = _create_user(db_session, email="ordinary-member@example.com")
    _login(client, member.email)

    response = _request(client, method, path, body)

    assert response.status_code == 403
    assert response.json() == {
        "ok": False,
        "error": {
            "message": "需要系统管理权限",
            "code": "SYSTEM_MANAGER_REQUIRED",
        },
    }


@pytest.mark.parametrize(("method", "path", "body"), SYSTEM_MANAGEMENT_REQUESTS)
def test_system_management_endpoints_still_require_authentication(
    client: TestClient,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    response = _request(client, method, path, body)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "can_manage_system"),
    (("admin", False), ("member", True)),
)
def test_admin_and_delegated_system_manager_can_read_system_settings(
    client: TestClient,
    db_session: Session,
    role: str,
    can_manage_system: bool,
) -> None:
    user = _create_user(
        db_session,
        email=f"{role}-{can_manage_system}@example.com",
        role=role,
        can_manage_system=can_manage_system,
    )
    _login(client, user.email)

    response = client.get("/api/system-settings")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "settings" in response.json()["data"]


def test_delegated_system_manager_keeps_system_management_success_contracts(
    client: TestClient,
    db_session: Session,
) -> None:
    apply_schema(db_session.get_bind())
    manager = _create_user(
        db_session,
        email="delegated-manager@example.com",
        can_manage_system=True,
    )
    _login(client, manager.email)

    flat_update = client.put(
        "/api/system-settings",
        json={"readerTheme": "dark"},
    )
    assert flat_update.status_code == 200
    assert flat_update.json()["data"]["settings"]["readerTheme"] == "dark"

    wrapped_update = client.patch(
        "/api/system-settings",
        json={"settings": {"readerTheme": "light"}},
    )
    assert wrapped_update.status_code == 200
    assert wrapped_update.json()["data"]["settings"]["readerTheme"] == "light"

    events = client.get("/api/management/events")
    assert events.status_code == 200
    assert events.json()["ok"] is True

    cleared = client.delete("/api/management/events")
    assert cleared.status_code == 200
    assert cleared.json()["ok"] is True

    listed = client.get("/api/backups")
    assert listed.status_code == 200
    assert listed.json()["ok"] is True

    missing_detail = client.get("/api/backups/missing")
    assert missing_detail.status_code == 404
    missing_restore = client.post("/api/backups/missing/restore")
    assert missing_restore.status_code == 404

    created = client.post("/api/backups")
    assert created.status_code == 201
    backup_id = created.json()["data"]["backup"]["id"]

    detail = client.get(f"/api/backups/{backup_id}")
    assert detail.status_code == 200
    downloaded = client.get(f"/api/backups/{backup_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"

    deleted = client.delete(f"/api/backups/{backup_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"deleted": True, "id": backup_id}


def _schema_references(value: object) -> set[str]:
    if isinstance(value, dict):
        references = {
            item
            for key, item in value.items()
            if key == "$ref" and isinstance(item, str)
        }
        for item in value.values():
            references.update(_schema_references(item))
        return references
    if isinstance(value, list):
        references: set[str] = set()
        for item in value:
            references.update(_schema_references(item))
        return references
    return set()


def test_system_management_openapi_documents_requests_and_forbidden_contracts(
    client: TestClient,
) -> None:
    document = client.get("/openapi.json").json()

    update_operation = document["paths"]["/api/system-settings"]["put"]
    assert "#/components/schemas/UpdateSystemSettingsRequest" in _schema_references(
        update_operation["requestBody"]
    )

    restore_operation = document["paths"]["/api/backups/{backup_id}/restore"][
        "post"
    ]
    assert "#/components/schemas/BackupRestoreRequest" in _schema_references(
        restore_operation["requestBody"]
    )

    protected_operations = (
        ("/api/system-settings", "get"),
        ("/api/system-settings", "put"),
        ("/api/system-settings", "patch"),
        ("/api/management/events", "get"),
        ("/api/management/events", "delete"),
        ("/api/backups", "get"),
        ("/api/backups", "post"),
        ("/api/backups/{backup_id}", "get"),
        ("/api/backups/{backup_id}", "delete"),
        ("/api/backups/{backup_id}/restore", "post"),
        ("/api/backups/{backup_id}/download", "get"),
    )
    for path, method in protected_operations:
        operation = document["paths"][path][method]
        assert "403" in operation["responses"], (method, path)
        assert any(
            "SystemManagerRequiredBody" in reference
            for reference in _schema_references(operation["responses"]["403"])
        ), (method, path)

    create_backup_responses = document["paths"]["/api/backups"]["post"]["responses"]
    assert "201" in create_backup_responses
    assert "200" not in create_backup_responses
