import pytest
from sqlalchemy import select

from app.core.auth import create_session
from app.models.auth import User, UserLibraryAccess
from app.models.settings import SystemEvent, SystemSetting
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.infrastructure.models import AutomationGrantRow
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)

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


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://different.invalid"}])
def test_management_cookie_secret_and_ownership(client, db_session, headers):
    enable_service(db_session)
    sign_in(client, db_session, "first")
    response = client.post(
        "/api/automation/grants", headers=headers, json=grant_request()
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
        json=grant_request(scopes=["system:read", "system:manage"]),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "SYSTEM_MANAGER_REQUIRED"
    response = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request(user_id="admin")
    )
    assert response.status_code == 422
    assert list(db_session.scalars(select(AutomationGrantRow))) == []


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://different.invalid"}])
def test_service_off_by_default_admin_only_activation_and_no_generic_bypass(
    client, db_session, headers
):
    sign_in(client, db_session, "manager", manager=True)
    initial = client.get("/api/automation/settings")
    assert initial.status_code == 200, initial.text
    assert initial.json()["data"]["enabled"] is False
    payload = {"enabled": True, "publicBaseUrl": "https://books.example/books"}
    assert (
        client.put("/api/automation/settings", headers=headers, json=payload).status_code
        == 403
    )
    blocked = client.put(
        "/api/system-settings", json={"settings": {"automation.mcp": "{}"}}
    )
    assert blocked.status_code == 400
    assert blocked.json()["error"]["code"] == "AUTOMATION_SETTINGS_ENDPOINT_REQUIRED"
    sign_in(client, db_session, "admin", admin=True)
    enabled = client.put("/api/automation/settings", headers=headers, json=payload)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"]["publicBaseUrl"] == "https://books.example/books"
    assert client.get("/api/automation/settings").json()["data"]["enabled"] is True
    # Generic settings DTO has no nested automation object, and cannot mutate it.
    generic = client.get("/api/system-settings")
    assert generic.status_code == 200, generic.text
    assert "automation.mcp" not in generic.json()["data"]["settings"]


@pytest.mark.parametrize(
    "url",
    [
        "http://books.example:8080/books",
        "http://192.168.1.10/books",
        "http://[::1]:8080/books",
        "https://books.example/books",
    ],
)
def test_http_and_https_activation_without_extra_permission(client, db_session, url):
    sign_in(client, db_session, "admin", admin=True)
    response = client.put(
        "/api/automation/settings",
        headers=ORIGIN,
        json={"enabled": True, "publicBaseUrl": url},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["publicBaseUrl"] == url
    for invalid_url in (
        "https://user:pass@example.com",
        "https://example.com?token=secret",
        "https://example.com/../escape",
    ):
        invalid = client.put(
            "/api/automation/settings",
            headers=ORIGIN,
            json={"enabled": True, "publicBaseUrl": invalid_url},
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
    enable_service(db_session)
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


def enable_service(db, scopes=frozenset({"system:read"})):
    SqlAlchemyAutomationSettings(db).save(
        AutomationServiceSettings(enabled=True, enabled_scopes=scopes, public_base_url="http://testserver")
    )
    db.commit()


def test_old_http_option_does_not_restrict_or_reappear(client, db_session):
    sign_in(client, db_session, "admin", admin=True)
    db_session.add(
        SystemSetting(
            key="automation.mcp",
            value='{"enabled": true, "public_base_url": "http://books.example/books", "allow_insecure_http": false, "enabled_scopes": ["system:read"]}',
        )
    )
    db_session.commit()
    response = client.get("/api/automation/settings")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["publicBaseUrl"] == "http://books.example/books"
    assert "allowInsecureHttp" not in response.text


def test_update_grant_keeps_token_expiry_and_enforces_owner(
    client, db_session, test_settings
):
    from app.bootstrap.automation import build_automation_authorizer
    from app.modules.automation.domain.access import ALL_SCOPES

    enable_service(db_session, frozenset({"system:read", "shelves:write"}))
    sign_in(client, db_session, "editor")
    created = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]
    grant = created["grant"]
    path = f"/api/automation/grants/{grant['id']}"
    body = grant_request(
        name="Renamed",
        libraryScope="all",
        libraryIds=[],
        scopes=["system:read", "shelves:write"],
    )
    changed = client.patch(path, json=body)
    assert changed.status_code == 200, changed.text
    assert changed.headers["cache-control"] == "no-store"
    updated = changed.json()["data"]["grant"]
    assert updated["name"] == "Renamed"
    assert updated["expiresAtMs"] == grant["expiresAtMs"]
    assert updated["id"] == grant["id"]
    assert created["token"] not in changed.text
    assert (
        client.post(path + "/reveal", headers=ORIGIN).json()["data"]["token"]
        == created["token"]
    )
    access = build_automation_authorizer(db_session).bearer(
        "Bearer " + created["token"], service_enabled=True, enabled_scopes=ALL_SCOPES
    )
    assert "shelves:write" in access.permissions.scopes
    body["scopes"] = ["system:read"]
    body["lifetimeDays"] = None
    updated = client.patch(path, headers=ORIGIN, json=body).json()["data"]["grant"]
    assert updated["expiresAtMs"] is None
    access = build_automation_authorizer(db_session).bearer(
        "Bearer " + created["token"], service_enabled=True, enabled_scopes=ALL_SCOPES
    )
    assert "shelves:write" not in access.permissions.scopes
    assert (
        client.patch(
            path,
            headers=ORIGIN,
            json={**body, "scopes": ["system:read", "files:modify"]},
        ).status_code
        == 403
    )
    client.cookies.clear()
    assert (
        client.patch(
            path,
            headers={**ORIGIN, "Authorization": "Bearer " + created["token"]},
            json=body,
        ).status_code
        == 401
    )
    sign_in(client, db_session, "other-editor")
    assert client.patch(path, headers=ORIGIN, json=body).status_code == 404


@pytest.mark.parametrize("inactive", ["revoked", "expired"])
def test_update_cannot_reactivate_grants(client, db_session, inactive):
    enable_service(db_session)
    sign_in(client, db_session, "editor")
    grant = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]["grant"]
    row = db_session.get(AutomationGrantRow, grant["id"])
    if inactive == "revoked":
        row.revoked_at_ms = 1
    else:
        row.expires_at_ms = 1
    db_session.commit()
    response = client.patch(
        f"/api/automation/grants/{grant['id']}",
        headers=ORIGIN,
        json=grant_request(lifetimeDays=None),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "GRANT_INACTIVE"


def test_service_allowance_controls_new_grant_scopes(client, db_session):
    enable_service(db_session)
    sign_in(client, db_session, "admin", admin=True)
    extra = grant_request(scopes=["system:read", "files:modify"])
    rejected = client.post("/api/automation/grants", json=extra)
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "SCOPE_REQUIRED"
    assert list(db_session.scalars(select(AutomationGrantRow))) == []
    created = client.post("/api/automation/grants", json=grant_request()).json()["data"]
    path = f"/api/automation/grants/{created['grant']['id']}"
    assert client.patch(path, json=extra).status_code == 403
    assert client.get("/api/automation/grants").json()["data"]["grants"][0]["scopes"] == ["system:read"]
    enable_service(db_session, frozenset({"system:read", "files:modify"}))
    assert client.patch(path, json=extra).status_code == 200
    enable_service(db_session)
    assert client.patch(path, json={**extra, "name": "Keep existing"}).status_code == 200
    assert client.patch(path, json=grant_request()).status_code == 200
    assert client.patch(path, json=extra).status_code == 403


@pytest.mark.parametrize("value,expected", [
    ("https://BOOKS.example/books", "https://books.example/books"),
    ("https://books.example:443/books", "https://books.example/books"),
    ("http://books.example:80/books", "http://books.example/books"),
    ("http://BOOKS.example:12443/books", "http://books.example:12443/books"),
    ("http://[0:0:0:0:0:0:0:1]:80/books", "http://[::1]/books"),
])
def test_public_url_matches_client_and_sdk(client, db_session, value, expected):
    import asyncio
    from urllib.parse import urlsplit

    import httpx
    from mcp.server.transport_security import (
        TransportSecurityMiddleware,
        TransportSecuritySettings,
    )
    from starlette.requests import Request

    sign_in(client, db_session, "admin", admin=True)
    saved = client.put("/api/automation/settings", json={"enabled": True, "publicBaseUrl": value})
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["publicBaseUrl"] == expected
    # Existing saved configurations are normalized on read too.
    SqlAlchemyAutomationSettings(db_session).save(
        AutomationServiceSettings(enabled=True, public_base_url=value)
    )
    db_session.commit()
    assert client.get("/api/automation/settings").json()["data"]["publicBaseUrl"] == expected
    public = urlsplit(expected)
    outgoing = httpx.Request("GET", expected + "/api/mcp")
    middleware = TransportSecurityMiddleware(TransportSecuritySettings(
        allowed_hosts=[public.netloc], allowed_origins=[f"{public.scheme}://{public.netloc}"]
    ))
    request = Request({"type": "http", "method": "GET", "path": "/api/mcp",
                       "headers": [(b"host", outgoing.headers["host"].encode()),
                                   (b"origin", f"{public.scheme}://{public.netloc}".encode())]})
    assert asyncio.run(middleware.validate_request(request)) is None
    bad = Request({"type": "http", "method": "GET", "path": "/api/mcp",
                   "headers": [(b"host", b"other.invalid")]})
    assert asyncio.run(middleware.validate_request(bad)).status_code == 421
