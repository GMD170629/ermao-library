# ruff: noqa: S106

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from appv2.modules.accounts.application import (
    AccountConflict,
    AccountNotFound,
    AccountService,
    AuthenticationFailed,
    InvalidResetToken,
    SetupAlreadyCompleted,
)
from appv2.modules.accounts.contracts import ALL_SCOPES, MEMBER_SCOPES, AccountView


class AccountsUnitOfWork:
    def __init__(self) -> None:
        self.accounts = MagicMock()
        self.sessions = MagicMock()
        self.password_resets = MagicMock()
        self.commits = 0
        self.commit_error: Exception | None = None

    def __enter__(self) -> AccountsUnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        if self.commit_error is not None:
            raise self.commit_error
        self.commits += 1

    def rollback(self) -> None:
        return None


def account_view(
    *,
    account_id: uuid.UUID | None = None,
    email: str = "reader@example.com",
    role: str = "member",
) -> AccountView:
    return AccountView(
        id=account_id or uuid.uuid4(),
        email=email,
        display_name="Reader",
        role=role,
        locale="en-US",
        scopes=ALL_SCOPES if role == "admin" else MEMBER_SCOPES,
        disabled=False,
        monitor_folder_ids=(),
        created_at=datetime.now(UTC),
    )


def account_service(
    unit: AccountsUnitOfWork,
) -> tuple[AccountService, MagicMock, MagicMock]:
    hasher = MagicMock()
    hasher.hash.return_value = "hashed-password"
    hasher.verify.return_value = True
    notice = MagicMock()
    notice.path = Path("/storage/v2/control/reset-password.html")
    notice.write.return_value = notice.path
    service = AccountService(
        uow_factory=lambda: unit,
        password_hasher=hasher,
        session_secret="test-session-secret",
        session_ttl_seconds=3600,
        password_reset_notice=notice,
        password_reset_ttl_seconds=1800,
    )
    return service, hasher, notice


def test_setup_login_session_and_logout_paths() -> None:
    unit = AccountsUnitOfWork()
    service, hasher, _notice = account_service(unit)
    admin = account_view(role="admin")
    unit.accounts.count_users.return_value = 0
    assert service.setup_required() is True
    unit.accounts.add_user.return_value = admin
    grant = service.setup(
        email="ADMIN@EXAMPLE.COM",
        display_name=" Admin ",
        password="correct horse battery staple",
        locale="en-US",
    )
    assert grant.account is admin
    unit.sessions.add.assert_called_once()
    unit.accounts.count_users.return_value = 1
    assert service.setup_required() is False
    with pytest.raises(SetupAlreadyCompleted):
        service.setup(
            email="admin@example.com",
            display_name="Admin",
            password="correct horse battery staple",
            locale="en-US",
        )

    unit.accounts.get_user_by_email.return_value = admin
    unit.accounts.password_hash_for.return_value = "stored-hash"
    login = service.login(email="ADMIN@EXAMPLE.COM", password="password")
    assert login.account is admin
    hasher.verify.assert_called()
    unit.accounts.get_user_by_email.return_value = None
    with pytest.raises(AuthenticationFailed):
        service.login(email="missing@example.com", password="password")
    unit.accounts.get_user_by_email.return_value = admin
    hasher.verify.return_value = False
    with pytest.raises(AuthenticationFailed):
        service.login(email="admin@example.com", password="wrong")

    unit.sessions.account_for.return_value = admin
    assert service.authenticate("session-token") is admin
    unit.sessions.account_for.return_value = None
    with pytest.raises(AuthenticationFailed):
        service.authenticate("expired-token")
    service.logout("session-token")
    unit.sessions.revoke.assert_called()


def test_user_management_account_updates_and_preferences() -> None:
    unit = AccountsUnitOfWork()
    service, hasher, _notice = account_service(unit)
    admin = account_view(role="admin")
    member = account_view()
    unit.accounts.list_users.return_value = ([admin, member], 2)
    assert service.list_users(page=1, page_size=24) == ([admin, member], 2)

    unit.accounts.email_in_use.return_value = False
    unit.accounts.add_user.return_value = member
    assert (
        service.create_user(
            email=member.email,
            display_name=member.display_name,
            password="correct horse battery staple",
            role="member",
            locale="en-US",
            scopes=MEMBER_SCOPES,
            monitor_folder_ids=(uuid.uuid4(),),
        )
        is member
    )
    with pytest.raises(ValueError):
        service.create_user(
            email=member.email,
            display_name=member.display_name,
            password="correct horse battery staple",
            role="owner",
            locale="en-US",
        )
    unit.accounts.email_in_use.return_value = True
    with pytest.raises(AccountConflict):
        service.create_user(
            email=member.email,
            display_name=member.display_name,
            password="correct horse battery staple",
            role="member",
            locale="en-US",
        )

    unit.accounts.email_in_use.return_value = False
    unit.accounts.password_hash_for.return_value = "stored-hash"
    unit.accounts.update_user.return_value = member
    hasher.verify.return_value = True
    assert (
        service.update_account(
            member.id,
            email="new@example.com",
            display_name="New Name",
            password="new correct horse battery staple",
            current_password="current password",
            locale="zh-CN",
        )
        is member
    )
    unit.sessions.revoke_user.assert_called_with(member.id)
    hasher.verify.return_value = False
    with pytest.raises(AuthenticationFailed):
        service.update_account(
            member.id,
            email="new@example.com",
            current_password="wrong",
        )
    hasher.verify.return_value = True
    unit.accounts.email_in_use.return_value = True
    with pytest.raises(AccountConflict):
        service.update_account(
            member.id,
            email="used@example.com",
            current_password="current password",
        )
    unit.accounts.email_in_use.return_value = False
    unit.accounts.update_user.return_value = None
    with pytest.raises(AccountNotFound):
        service.update_account(member.id, display_name="Missing")

    unit.accounts.update_user.return_value = member
    assert (
        service.update_managed_user(
            member.id,
            email="managed@example.com",
            display_name="Managed",
            role="admin",
            disabled=False,
            locale="en-US",
            scopes=None,
            monitor_folder_ids=(),
        )
        is member
    )
    unit.accounts.email_in_use.return_value = True
    with pytest.raises(AccountConflict):
        service.update_managed_user(
            member.id,
            email="used@example.com",
            display_name=None,
            role=None,
            disabled=None,
            locale=None,
            scopes=None,
            monitor_folder_ids=None,
        )
    unit.accounts.email_in_use.return_value = False
    unit.accounts.update_user.return_value = None
    with pytest.raises(AccountNotFound):
        service.update_managed_user(
            member.id,
            email=None,
            display_name=None,
            role=None,
            disabled=None,
            locale=None,
            scopes=None,
            monitor_folder_ids=None,
        )
    with pytest.raises(ValueError):
        service.update_managed_user(
            member.id,
            email=None,
            display_name=None,
            role="owner",
            disabled=None,
            locale=None,
            scopes=None,
            monitor_folder_ids=None,
        )

    unit.accounts.update_user.return_value = member
    assert service.set_managed_password(member.id, "new password value") is member
    unit.accounts.update_user.return_value = None
    with pytest.raises(AccountNotFound):
        service.set_managed_password(member.id, "new password value")
    unit.accounts.delete_user.return_value = True
    service.delete_user(member.id)
    unit.accounts.delete_user.return_value = False
    with pytest.raises(AccountNotFound):
        service.delete_user(member.id)
    unit.accounts.preferences.return_value = {"view": "grid"}
    assert service.preferences(member.id) == {"view": "grid"}
    unit.accounts.save_preferences.return_value = {"view": "list"}
    assert service.save_preferences(member.id, {"view": "list"}) == {"view": "list"}


def test_password_reset_request_confirm_and_cleanup() -> None:
    unit = AccountsUnitOfWork()
    service, _hasher, notice = account_service(unit)
    member = account_view()
    unit.accounts.get_user_by_email.return_value = None
    assert service.request_password_reset(
        email="missing@example.com",
        app_base_url="https://books.example.com",
    ) == Path("/storage/v2/control/reset-password.html")
    notice.write.assert_not_called()

    unit.accounts.get_user_by_email.return_value = member
    path = service.request_password_reset(
        email=member.email,
        app_base_url="https://books.example.com/",
    )
    assert path == notice.path
    reset_url = notice.write.call_args.kwargs["reset_url"]
    assert reset_url.startswith("https://books.example.com/reset-password#token=")
    unit.password_resets.issue.assert_called_once()

    unit.commit_error = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        service.request_password_reset(
            email=member.email,
            app_base_url="https://books.example.com",
        )
    notice.clear.assert_called_once()
    unit.commit_error = None

    unit.password_resets.consume.return_value = None
    with pytest.raises(InvalidResetToken):
        service.confirm_password_reset(
            token="invalid-reset-token",
            new_password="new correct horse battery staple",
        )
    unit.password_resets.consume.return_value = member.id
    unit.accounts.update_user.return_value = None
    with pytest.raises(InvalidResetToken):
        service.confirm_password_reset(
            token="valid-reset-token",
            new_password="new correct horse battery staple",
        )
    unit.accounts.update_user.return_value = member
    service.confirm_password_reset(
        token="valid-reset-token",
        new_password="new correct horse battery staple",
    )
    unit.sessions.revoke_user.assert_called_with(member.id)
    assert notice.clear.call_count == 2
