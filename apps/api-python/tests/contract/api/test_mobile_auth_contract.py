from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models.auth import User

MOBILE_AUTH_EMAIL = "mobile-auth@example.com"
MOBILE_AUTH_PASSWORD = "MobileAuthContract123!"


def _create_mobile_user(
    db_session: Session,
    *,
    status: str = "active",
) -> User:
    user = User(
        email=MOBILE_AUTH_EMAIL,
        name="Mobile contract",
        password_hash=hash_password(MOBILE_AUTH_PASSWORD),
        role="member",
        status=status,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_mobile_setup_status_and_setup_contract(
    client: TestClient,
) -> None:
    status = client.get("/api/auth/setup/status")

    assert status.status_code == 200
    assert status.headers["cache-control"] == "no-store"
    assert status.json() == {"ok": True, "data": {"initialized": False}}

    created = client.post(
        "/api/auth/setup",
        json={
            "name": "  Mobile owner  ",
            "email": " MOBILE-OWNER@EXAMPLE.COM ",
            "password": MOBILE_AUTH_PASSWORD,
            "locale": "en-US",
        },
    )

    assert created.status_code == 201
    payload = created.json()
    assert payload["ok"] is True
    assert payload["data"]["initialized"] is True
    assert payload["data"]["user"] == {
        "id": payload["data"]["user"]["id"],
        "email": "mobile-owner@example.com",
        "name": "Mobile owner",
        "role": "admin",
        "status": "active",
        "canManageSystem": False,
        "canViewManualImports": False,
        "authzVersion": 1,
        "avatarUrl": None,
        "locale": "en-US",
    }
    assert payload["data"]["authorization"]["isAdmin"] is True
    assert payload["data"]["preferences"]["locale"] == "en-US"
    assert "shuku_session" in created.cookies
    assert created.cookies["shuku_locale"] == "en-US"

    verified = client.get("/api/auth/me")
    assert verified.status_code == 200
    assert verified.json()["data"]["user"]["id"] == payload["data"]["user"]["id"]


def test_mobile_setup_validation_and_concurrent_setup_contract(
    client: TestClient,
) -> None:
    invalid = client.post(
        "/api/auth/setup",
        json={
            "name": "Owner",
            "email": "not-an-email",
            "password": "short",
            "locale": "fr-FR",
        },
    )

    assert invalid.status_code == 422
    assert invalid.json()["ok"] is False
    invalid_fields = {error["loc"][-1] for error in invalid.json()["error"]["details"]}
    assert invalid_fields == {"email", "password", "locale"}

    first = client.post(
        "/api/auth/setup",
        json={
            "name": "Owner",
            "email": "owner@example.com",
            "password": MOBILE_AUTH_PASSWORD,
            "locale": "zh-CN",
        },
    )
    assert first.status_code == 201

    conflict = client.post(
        "/api/auth/setup",
        json={
            "name": "Other owner",
            "email": "other@example.com",
            "password": MOBILE_AUTH_PASSWORD,
            "locale": "zh-CN",
        },
    )

    assert conflict.status_code == 409
    assert conflict.json()["ok"] is False

    status = client.get("/api/auth/setup/status")
    assert status.json() == {"ok": True, "data": {"initialized": True}}


def test_mobile_login_me_and_logout_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    user = _create_mobile_user(db_session)

    login = client.post(
        "/api/auth/login",
        json={
            "email": f" {MOBILE_AUTH_EMAIL.upper()} ",
            "password": MOBILE_AUTH_PASSWORD,
        },
    )

    assert login.status_code == 200
    assert login.json()["data"]["user"]["id"] == user.id
    assert login.json()["data"]["authorization"]["authzVersion"] == 1
    assert "shuku_session" in login.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["data"] == login.json()["data"]

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"ok": True, "data": {"loggedOut": True}}

    unauthorized = client.get("/api/auth/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["ok"] is False


def test_mobile_login_failure_taxonomy_contract(
    client: TestClient,
    db_session: Session,
) -> None:
    _create_mobile_user(db_session)

    invalid_credentials = client.post(
        "/api/auth/login",
        json={"email": MOBILE_AUTH_EMAIL, "password": "wrong-password"},
    )
    assert invalid_credentials.status_code == 401
    assert invalid_credentials.json()["ok"] is False

    user = db_session.scalar(select(User).where(User.email == MOBILE_AUTH_EMAIL))
    assert user is not None
    user.status = "disabled"
    db_session.commit()

    disabled = client.post(
        "/api/auth/login",
        json={"email": MOBILE_AUTH_EMAIL, "password": MOBILE_AUTH_PASSWORD},
    )
    assert disabled.status_code == 403
    assert disabled.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_mobile_login_requires_setup_and_refresh_requires_session(
    client: TestClient,
) -> None:
    setup_required = client.post(
        "/api/auth/login",
        json={"email": MOBILE_AUTH_EMAIL, "password": MOBILE_AUTH_PASSWORD},
    )
    assert setup_required.status_code == 409
    assert setup_required.json()["error"]["details"] == {"code": "SETUP_REQUIRED"}

    refresh = client.post("/api/auth/session/refresh")
    assert refresh.status_code == 401
    assert refresh.json()["ok"] is False


def test_mobile_auth_openapi_contract(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    expected_operations = {
        ("/api/auth/setup/status", "get"): (200, None),
        ("/api/auth/setup", "post"): (201, "SetupRequest"),
        ("/api/auth/login", "post"): (200, "LoginRequest"),
        ("/api/auth/me", "get"): (200, None),
        ("/api/auth/session/refresh", "post"): (200, None),
        ("/api/auth/logout", "post"): (200, None),
    }
    for (path, method), (success_status, request_schema) in expected_operations.items():
        operation = paths[path][method]
        assert str(success_status) in operation["responses"]
        if request_schema is None:
            assert "requestBody" not in operation
        else:
            schema = operation["requestBody"]["content"]["application/json"]["schema"]
            assert schema["$ref"].endswith(f"/{request_schema}")

    assert {"409", "422"} <= paths["/api/auth/setup"]["post"]["responses"].keys()
    assert {"401", "403", "409", "422"} <= paths["/api/auth/login"]["post"][
        "responses"
    ].keys()
    assert "401" in paths["/api/auth/me"]["get"]["responses"]
    assert {"401", "503"} <= paths["/api/auth/session/refresh"]["post"][
        "responses"
    ].keys()
