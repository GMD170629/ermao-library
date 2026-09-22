from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import select, update

from app.bootstrap.automation import build_automation_authorizer, build_grant_manager
from app.core.auth import create_session
from app.models import Library
from app.models.auth import UserLibraryAccess
from app.models.settings import SystemEvent
from app.modules.automation.domain.access import (
    ALL_SCOPES,
    AutomationAccessError,
    GrantPermissions,
    Scope,
)
from app.modules.automation.infrastructure.models import AutomationGrantRow
from app.modules.automation.infrastructure.token_vault import AutomationTokenVault
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)
from tests.integration.modules.automation.test_management_http import (
    ORIGIN,
    enable_service,
    grant_request,
    sign_in,
)


def test_vault_binding_corruption_and_immutable_key(tmp_path):
    vault = AutomationTokenVault(tmp_path / "secrets")
    encrypted = vault.encrypt("owner", "grant", "secret", initialize=True)
    assert "secret" not in encrypted
    assert vault.decrypt("owner", "grant", encrypted) == "secret"
    key = tmp_path / "secrets/automation-token.key"
    original = key.read_bytes()
    assert key.stat().st_mode & 0o777 == 0o600
    for user, grant, value in [
        ("other", "grant", encrypted),
        ("owner", "other", encrypted),
        ("owner", "grant", encrypted[:-4] + "AAAA"),
    ]:
        with pytest.raises(AutomationAccessError, match="TOKEN_DECRYPTION_FAILED"):
            vault.decrypt(user, grant, value)
    key.write_bytes(b"invalid")
    with pytest.raises(AutomationAccessError, match="TOKEN_KEY_INVALID"):
        vault.encrypt("owner", "grant", "secret", initialize=True)
    assert key.read_bytes() == b"invalid"
    key.unlink()
    with pytest.raises(AutomationAccessError, match="TOKEN_KEY_UNAVAILABLE"):
        vault.decrypt("owner", "grant", encrypted)
    with pytest.raises(AutomationAccessError, match="TOKEN_KEY_UNAVAILABLE"):
        vault.encrypt("owner", "new", "secret", initialize=False)
    assert not key.exists()
    key.write_bytes(original)
    key.chmod(0o600)
    assert vault.decrypt("owner", "grant", encrypted) == "secret"


def test_concurrent_key_creation_uses_one_complete_key(tmp_path):
    def issue(index):
        return AutomationTokenVault(tmp_path).encrypt(
            "owner", str(index), str(index), initialize=True
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(issue, range(16)))
    vault = AutomationTokenVault(tmp_path)
    assert [
        vault.decrypt("owner", str(i), value) for i, value in enumerate(values)
    ] == list(map(str, range(16)))
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("headers", [{}, {"Origin": "https://different.invalid"}])
def test_reveal_cookie_owner_cache_revocation_and_service_off(
    client, db_session, test_settings, caplog, headers
):
    enable_service(db_session)
    sign_in(client, db_session, "owner")
    created = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]
    token, grant_id = created["token"], created["grant"]["id"]
    path = f"/api/automation/grants/{grant_id}/reveal"
    response = client.post(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["token"] == token
    assert response.headers["cache-control"] == "no-store"
    assert token not in client.get("/api/automation/grants").text
    row = db_session.get(AutomationGrantRow, grant_id)
    assert token not in row.token_ciphertext and row.library_scope == "selected"
    assert (
        build_grant_manager(db_session, test_settings).reveal(
            user_id="owner", grant_id=grant_id
        )
        == token
    )
    settings = SqlAlchemyAutomationSettings(db_session)
    settings.save(replace(settings.load(), enabled=False))
    db_session.commit()
    denied = client.post("/api/automation/grants", headers=ORIGIN, json=grant_request())
    assert denied.json()["error"]["code"] == "AUTOMATION_DISABLED"
    assert client.post(path, headers=ORIGIN).json()["data"]["token"] == token
    client.cookies.clear()
    assert (
        client.post(
            path, headers={**ORIGIN, "Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    sign_in(client, db_session, "other")
    assert client.post(path, headers=ORIGIN).status_code == 404
    _, cookie = create_session(db_session, "owner")
    db_session.commit()
    client.cookies.set("shuku_session", cookie)
    assert (
        client.delete(f"/api/automation/grants/{grant_id}", headers=headers).status_code
        == 200
    )
    assert client.post(path, headers=ORIGIN).json()["error"]["code"] == "GRANT_INACTIVE"
    db_session.expire_all()
    assert db_session.get(AutomationGrantRow, grant_id).token_ciphertext is None
    for event in db_session.scalars(select(SystemEvent)):
        assert token not in str((event.message, event.metadata_json))
    assert token not in caplog.text


def test_legacy_expired_and_lost_key_never_regenerates(
    client, db_session, test_settings
):
    enable_service(db_session)
    sign_in(client, db_session, "owner")
    manager = build_grant_manager(db_session, test_settings)
    permissions = GrantPermissions(
        frozenset({Scope.SYSTEM_READ}), frozenset(), library_scope="all"
    )
    created = manager.create(user_id="owner", name="Encrypted", permissions=permissions)
    key = test_settings.resolved_storage_root / "secrets/automation-token.key"
    key.unlink()
    with pytest.raises(AutomationAccessError, match="TOKEN_KEY_UNAVAILABLE"):
        manager.create(user_id="owner", name="New", permissions=permissions)
    assert not key.exists()
    path = f"/api/automation/grants/{created.grant.id}/reveal"
    assert (
        client.post(path, headers=ORIGIN).json()["error"]["code"]
        == "TOKEN_KEY_UNAVAILABLE"
    )
    db_session.execute(
        update(AutomationGrantRow)
        .where(AutomationGrantRow.id == created.grant.id)
        .values(token_ciphertext=None)
    )
    db_session.commit()
    assert (
        build_automation_authorizer(db_session)
        .bearer(
            f"Bearer {created.token}", service_enabled=True, enabled_scopes=ALL_SCOPES
        )
        .grant_id
        == created.grant.id
    )
    assert (
        client.post(path, headers=ORIGIN).json()["error"]["code"]
        == "TOKEN_NOT_RECOVERABLE"
    )
    db_session.execute(
        update(AutomationGrantRow)
        .where(AutomationGrantRow.id == created.grant.id)
        .values(expires_at_ms=1)
    )
    db_session.commit()
    assert client.post(path, headers=ORIGIN).json()["error"]["code"] == "GRANT_INACTIVE"


def test_dynamic_libraries_follow_current_access_and_fixed_grants_do_not_expand(
    client, db_session
):
    enable_service(db_session)
    sign_in(client, db_session, "owner")
    fixed = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]
    db_session.delete(
        db_session.scalar(
            select(UserLibraryAccess).where(UserLibraryAccess.user_id == "owner")
        )
    )
    db_session.commit()
    response = client.post(
        "/api/automation/grants",
        headers=ORIGIN,
        json={"name": "All", "libraryScope": "all"},
    )
    assert response.status_code == 200, response.text
    dynamic = response.json()["data"]
    assert dynamic["grant"]["libraryIds"] == []
    auth = build_automation_authorizer(db_session)

    def allowed(grant):
        return auth.bearer(
            f"Bearer {grant['token']}", service_enabled=True, enabled_scopes=ALL_SCOPES
        ).permissions.library_ids

    assert allowed(dynamic) == frozenset()
    db_session.add(
        Library(
            id="new-library", name="New", root_path="/unused", organization_mode="FLAT"
        )
    )
    db_session.flush()
    access = UserLibraryAccess(user_id="owner", library_id="new-library")
    db_session.add(access)
    db_session.commit()
    assert allowed(dynamic) == frozenset({"new-library"})
    assert allowed(fixed) == frozenset()
    db_session.delete(access)
    db_session.commit()
    assert allowed(dynamic) == frozenset()
    assert (
        client.post(
            "/api/automation/grants", headers=ORIGIN, json={"name": "Old request"}
        ).json()["error"]["code"]
        == "LIBRARY_NOT_FOUND"
    )


def test_explicit_non_expiring_grant_remains_valid_and_revocable(
    client, db_session, test_settings
):
    from app.modules.auth.infrastructure.automation_identity import (
        SqlAlchemyAutomationIdentity,
    )
    from app.modules.automation.application.grants import (
        AuthorizeAutomation,
        ManageGrants,
    )
    from app.modules.automation.infrastructure.credentials import AutomationCredentials
    from app.modules.automation.infrastructure.grants import SqlAlchemyGrantStore
    from app.modules.system.infrastructure.automation_audit import (
        SqlAlchemyAutomationAudit,
    )

    enable_service(db_session)
    sign_in(client, db_session, "owner")
    response = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request(lifetimeDays=None)
    )
    assert response.status_code == 200, response.text
    created = response.json()["data"]
    assert created["grant"]["expiresAtMs"] is None
    store = SqlAlchemyGrantStore(db_session)
    from app.modules.library.infrastructure.automation_access import (
        SqlAlchemyVisibleLibraryIds,
    )

    identity = SqlAlchemyAutomationIdentity(
        db_session, SqlAlchemyVisibleLibraryIds(db_session)
    )
    future = lambda: 9_000_000_000_000
    authorizer = AuthorizeAutomation(store, identity, AutomationCredentials(), future)
    manager = ManageGrants(
        store,
        identity,
        AutomationCredentials(),
        db_session,
        future,
        SqlAlchemyAutomationAudit(db_session),
        AutomationTokenVault(test_settings.resolved_storage_root / "secrets"),
        lambda: True,
    )
    assert manager.list_owned("owner")[0].expires_at_ms is None
    assert (
        manager.reveal(user_id="owner", grant_id=created["grant"]["id"])
        == created["token"]
    )
    assert (
        authorizer.bearer(
            f"Bearer {created['token']}",
            service_enabled=True,
            enabled_scopes=ALL_SCOPES,
        ).grant_id
        == created["grant"]["id"]
    )
    manager.revoke(user_id="owner", grant_id=created["grant"]["id"])
    with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
        authorizer.bearer(
            f"Bearer {created['token']}",
            service_enabled=True,
            enabled_scopes=ALL_SCOPES,
        )
    ordinary = client.post(
        "/api/automation/grants", headers=ORIGIN, json=grant_request()
    ).json()["data"]["grant"]
    assert ordinary["expiresAtMs"] - ordinary["createdAtMs"] == 90 * 86_400_000
