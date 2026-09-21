import pytest
from sqlalchemy import select

from app.core.auth import create_session
from app.models.auth import User, UserLibraryAccess
from app.models.settings import SystemEvent, SystemSetting
from app.modules.automation.infrastructure.models import AutomationGrantRow

ORIGIN = {"Origin": "http://testserver"}


def sign_in(client, db, user_id, *, admin=False, manager=False):
    db.add(
        User(
            id=user_id,
            email=f"{user_id}@test.invalid",
            name=user_id,
            password_hash="unused",
            role="admin" if admin else "member",
            can_manage_system=manager,
        )
    )
    db.flush()
    if not admin:
        db.add(UserLibraryAccess(user_id=user_id, library_id="test-library"))
        db.flush()
    _, token = create_session(db, user_id)
    db.commit()
    client.cookies.set("shuku_session", token)


def grant_request(**overrides):
    return {"name": "Local model", "libraryIds": ["test-library"], **overrides}


def test_management_cookie_origin_one_time_secret_and_ownership(client, db_session):
    sign_in(client, db_session, "first")
    assert (
        client.post("/api/automation/grants", json=grant_request()).status_code == 403
    )
    assert (
        client.post(
            "/api/automation/grants",
            headers={"Origin": "https://evil.invalid"},
            json=grant_request(),
        ).status_code
        == 403
    )
    assert list(db_session.scalars(select(AutomationGrantRow))) == []
    response = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    created = response.json()["data"]
    token = created["token"]
    grant_id = created["grant"]["id"]
    listed = client.get("/api/automation/grants")
    assert token not in listed.text
    assert listed.json()["data"]["grants"][0]["id"] == grant_id
    client.cookies.clear()
    assert (
        client.get(
            "/api/automation/grants", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    sign_in(client, db_session, "second")
    assert client.get("/api/automation/grants").json()["data"]["grants"] == []
    assert (
        client.delete(f"/api/automation/grants/{grant_id}", headers=ORIGIN).status_code
        == 404
    )


def test_scope_creation_cannot_elevate_member(client, db_session):
    sign_in(client, db_session, "member")
    response = client.post(
        "/api/automation/grants",
        headers=ORIGIN,
        json=grant_request(scopes=["library:read", "files:read"]),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"
    response = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request(user_id="admin")
    )
    assert response.status_code == 422
    assert list(db_session.scalars(select(AutomationGrantRow))) == []


def test_service_off_by_default_admin_only_activation_and_no_generic_bypass(
    client, db_session
):
    sign_in(client, db_session, "manager", manager=True)
    initial = client.get("/api/automation/settings")
    assert initial.status_code == 200, initial.text
    assert initial.json()["data"]["enabled"] is False
    payload = {"enabled": True, "publicBaseUrl": "https://books.example/books"}
    assert (
        client.put("/api/automation/settings", headers=ORIGIN, json=payload).status_code
        == 403
    )
    blocked = client.put(
        "/api/system-settings", json={"settings": {"automation.mcp": "{}"}}
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "AUTOMATION_SETTINGS_ENDPOINT_REQUIRED"
    sign_in(client, db_session, "admin", admin=True)
    enabled = client.put("/api/automation/settings", headers=ORIGIN, json=payload)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["publicBaseUrl"] == "https://books.example/books"
    assert client.get("/api/automation/settings").json()["data"]["enabled"] is True
    # Generic settings DTO has no nested automation object, and cannot mutate it.
    generic = client.get("/api/system-settings")
    assert generic.status_code == 200, generic.text
    assert "automation.mcp" not in generic.json()["data"]["settings"]


def test_http_activation_requires_explicit_insecure_opt_in(client, db_session):
    sign_in(client, db_session, "admin", admin=True)
    payload = {"enabled": True, "publicBaseUrl": "http://books.example"}
    assert (
        client.put("/api/automation/settings", headers=ORIGIN, json=payload).json()[
            "error"
        ]["code"]
        == "HTTPS_REQUIRED"
    )
    payload["allowInsecureHttp"] = True
    assert (
        client.put("/api/automation/settings", headers=ORIGIN, json=payload).status_code
        == 200
    )
    for url in (
        "https://user:pass@example.com",
        "https://example.com?token=secret",
        "https://example.com/../escape",
    ):
        invalid = client.put(
            "/api/automation/settings",
            headers=ORIGIN,
            json={"enabled": True, "publicBaseUrl": url},
        )
        assert invalid.status_code == 400


@pytest.mark.parametrize(
    ("language", "message"),
    [
        ("zh-CN", "已创建自动化授权"),
        ("en-US", "Automation grant created"),
    ],
)
def test_audit_has_localized_message_and_never_credential(
    client, db_session, language, message
):
    sign_in(client, db_session, "member")
    db_session.add(SystemSetting(key="language", value=f'"{language}"'))
    db_session.commit()
    created = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]
    event = db_session.scalar(
        select(SystemEvent).where(SystemEvent.action == "automation.grant.created")
    )
    assert event.message == message
    assert event.actor_id == "member"
    assert event.target_id == created["grant"]["id"]
    assert created["token"] not in event.message
    assert created["token"] not in str(event.metadata_json)
