from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.automation import build_automation_authorizer, build_grant_manager
from app.models import Library
from app.models.auth import User
from app.models.settings import SystemEvent
from app.modules.automation.application.grants import AuthorizeAutomation, ManageGrants
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import (
    ALL_SCOPES,
    AutomationAccessError,
    AutomationActor,
    GrantPermissions,
    Scope,
)
from app.modules.automation.infrastructure.credentials import AutomationCredentials
from app.modules.automation.infrastructure.grants import SqlAlchemyGrantStore
from app.modules.automation.infrastructure.models import AutomationGrantRow
from app.modules.automation.infrastructure.token_vault import AutomationTokenVault
from app.modules.system.infrastructure.automation_audit import SqlAlchemyAutomationAudit
from app.modules.system.infrastructure.automation_settings import (
    SqlAlchemyAutomationSettings,
)


class Identities:
    def __init__(self):
        self.actor = AutomationActor("owner", True, True, frozenset({"test-library"}))

    def current_actor(self, user_id):
        return self.actor if self.actor.user_id == user_id else None


def test_credential_storage_reopen_revoke_and_current_permissions(db_session, tmp_path):
    db_session.add(
        User(
            id="owner", email="owner@test.invalid", name="Owner", password_hash="unused"
        )
    )
    db_session.commit()
    identities = Identities()
    credentials = AutomationCredentials()
    now = 1_800_000_000_000
    manager = ManageGrants(
        SqlAlchemyGrantStore(db_session),
        identities,
        credentials,
        db_session,
        lambda: now,
        SqlAlchemyAutomationAudit(db_session),
        AutomationTokenVault(tmp_path / "secrets"),
        lambda: True,
    )
    created = manager.create(
        user_id="owner",
        name="Local client",
        permissions=GrantPermissions(
            frozenset({Scope.LIBRARY_READ}), frozenset({"test-library"})
        ),
    )
    assert created.token not in repr(created)
    row = db_session.scalar(select(AutomationGrantRow))
    assert row.token_digest == credentials.digest(created.token)
    assert row.token_digest != created.token
    assert not hasattr(manager.list_owned("owner")[0], "token")

    def authorize(session, token=created.token, enabled=True):
        return AuthorizeAutomation(
            SqlAlchemyGrantStore(session), identities, credentials, lambda: now
        ).bearer(
            f"Bearer {token}",
            service_enabled=enabled,
            enabled_scopes=ALL_SCOPES,
        )

    with Session(db_session.get_bind()) as reopened:
        assert authorize(reopened).grant_id == created.grant.id
        with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
            authorize(reopened, token="shuku_session_cookie")
        with pytest.raises(AutomationAccessError, match="AUTOMATION_DISABLED"):
            authorize(reopened, enabled=False)
        identities.actor = replace(identities.actor, library_ids=frozenset())
        assert not authorize(reopened).permissions.library_ids
        identities.actor = replace(identities.actor, active=False)
        with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
            authorize(reopened)
        identities.actor = replace(identities.actor, active=True)
        manager.revoke(user_id="owner", grant_id=created.grant.id)
        with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
            authorize(reopened)
        with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
            AuthorizeAutomation(
                SqlAlchemyGrantStore(reopened), identities, credentials, lambda: now
            ).operation(
                grant_id=created.grant.id,
                user_id="owner",
                service_enabled=True,
                enabled_scopes=ALL_SCOPES,
            )


def test_expiry_exact_boundary_and_cannot_revoke_another_users_grant(
    db_session, tmp_path
):
    db_session.add(
        User(
            id="owner", email="owner@test.invalid", name="Owner", password_hash="unused"
        )
    )
    db_session.commit()
    identity = Identities()
    credential = AutomationCredentials()
    store = SqlAlchemyGrantStore(db_session)
    now = 1_800_000_000_000
    manager = ManageGrants(
        store,
        identity,
        credential,
        db_session,
        lambda: now,
        SqlAlchemyAutomationAudit(db_session),
        AutomationTokenVault(tmp_path / "secrets"),
        lambda: True,
    )
    created = manager.create(
        user_id="owner",
        name="Reader",
        lifetime_days=30,
        permissions=GrantPermissions(
            frozenset({Scope.LIBRARY_READ}), frozenset({"test-library"})
        ),
    )
    expiry = created.grant.expires_at_ms
    auth = AuthorizeAutomation(store, identity, credential, lambda: expiry)
    with pytest.raises(AutomationAccessError, match="UNAUTHORIZED"):
        auth.bearer(
            f"Bearer {created.token}", service_enabled=True, enabled_scopes=ALL_SCOPES
        )
    identity.actor = replace(identity.actor, user_id="other")
    with pytest.raises(AutomationAccessError, match="GRANT_NOT_FOUND"):
        manager.revoke(user_id="other", grant_id=created.grant.id)
    assert store.by_id(created.grant.id).revoked_at_ms is None


def test_real_identity_rechecks_admin_downgrade_and_library_scope(db_session, tmp_path):
    user = User(
        id="admin",
        email="admin@test.invalid",
        name="Admin",
        password_hash="unused",
        role="admin",
    )
    db_session.add(user)
    db_session.add(
        Library(id="other", name="Other", root_path="/other", organization_mode="FLAT")
    )
    db_session.commit()
    SqlAlchemyAutomationSettings(db_session).save(
        AutomationServiceSettings(enabled=True, public_base_url="http://localhost")
    )
    db_session.commit()
    created = build_grant_manager(db_session).create(
        user_id="admin",
        name="Bounded",
        permissions=GrantPermissions(
            frozenset({Scope.LIBRARY_READ, Scope.FILES_READ}),
            frozenset({"test-library"}),
        ),
    )
    with Session(db_session.get_bind()) as separate:
        authorizer = build_automation_authorizer(separate)
        result = authorizer.bearer(
            f"Bearer {created.token}",
            service_enabled=True,
            enabled_scopes=ALL_SCOPES,
        )
        assert result.permissions.library_ids == frozenset({"test-library"})
        with pytest.raises(AutomationAccessError, match="RESOURCE_NOT_FOUND"):
            result.require(Scope.FILES_READ, library_ids=frozenset({"other"}))
        user.role = "member"
        db_session.commit()
        result = authorizer.bearer(
            f"Bearer {created.token}",
            service_enabled=True,
            enabled_scopes=ALL_SCOPES,
        )
        assert result.permissions.scopes == frozenset({Scope.LIBRARY_READ})
        assert result.permissions.library_ids == frozenset()


def test_audit_failure_rolls_back_grant_and_event_together(db_session, tmp_path):
    db_session.add(
        User(
            id="owner", email="owner@test.invalid", name="Owner", password_hash="unused"
        )
    )
    db_session.commit()

    class FailingAudit(SqlAlchemyAutomationAudit):
        def write(self, event):
            super().write(event)
            raise RuntimeError("injected audit persistence failure")

    manager = ManageGrants(
        SqlAlchemyGrantStore(db_session),
        Identities(),
        AutomationCredentials(),
        db_session,
        lambda: 1_800_000_000_000,
        FailingAudit(db_session),
        AutomationTokenVault(tmp_path / "secrets"),
        lambda: True,
    )
    with pytest.raises(RuntimeError, match="injected audit"):
        manager.create(
            user_id="owner",
            name="Local",
            permissions=GrantPermissions(
                frozenset({Scope.LIBRARY_READ}), frozenset({"test-library"})
            ),
        )
    assert list(db_session.scalars(select(AutomationGrantRow))) == []
    assert list(db_session.scalars(select(SystemEvent))) == []
