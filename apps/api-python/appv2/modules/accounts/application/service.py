from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from appv2.modules.accounts.contracts import (
    ALL_SCOPES,
    MEMBER_SCOPES,
    AccessScope,
    AccountsUnitOfWork,
    AccountView,
    PasswordResetNoticePort,
    SessionGrant,
)
from appv2.modules.accounts.domain import User
from appv2.platform.auth import PasswordHasher, new_session_token, token_digest


class AccountsError(Exception):
    """Base class for expected account failures."""


class AuthenticationFailed(AccountsError):
    pass


class SetupAlreadyCompleted(AccountsError):
    pass


class AccountConflict(AccountsError):
    pass


class AccountNotFound(AccountsError):
    pass


class InvalidResetToken(AccountsError):
    pass


class AccountService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AccountsUnitOfWork],
        password_hasher: PasswordHasher,
        session_secret: str,
        session_ttl_seconds: int,
        password_reset_notice: PasswordResetNoticePort,
        password_reset_ttl_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._session_secret = session_secret
        self._session_ttl = timedelta(seconds=session_ttl_seconds)
        self._password_reset_notice = password_reset_notice
        self._password_reset_ttl = timedelta(seconds=password_reset_ttl_seconds)

    def setup_required(self) -> bool:
        with self._uow_factory() as uow:
            return uow.accounts.count_users() == 0

    def setup(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        locale: str,
    ) -> SessionGrant:
        normalized_email = User.normalize_email(email)
        normalized_name = User.normalize_display_name(display_name)
        password_hash = self._password_hasher.hash(password)
        with self._uow_factory() as uow:
            if uow.accounts.count_users() != 0:
                raise SetupAlreadyCompleted
            account = uow.accounts.add_user(
                email=normalized_email,
                display_name=normalized_name,
                password_hash=password_hash,
                role="admin",
                locale=locale,
                scopes=ALL_SCOPES,
            )
            grant = self._create_grant(uow, account)
            uow.commit()
            return grant

    def login(self, *, email: str, password: str) -> SessionGrant:
        normalized_email = User.normalize_email(email)
        with self._uow_factory() as uow:
            account = uow.accounts.get_user_by_email(normalized_email)
            password_hash = (
                uow.accounts.password_hash_for(account.id) if account is not None else None
            )
            if (
                account is None
                or password_hash is None
                or not self._password_hasher.verify(password, password_hash)
            ):
                raise AuthenticationFailed
            grant = self._create_grant(uow, account)
            uow.commit()
            return grant

    def authenticate(self, token: str) -> AccountView:
        now = datetime.now(UTC)
        digest = token_digest(token, self._session_secret)
        with self._uow_factory() as uow:
            account = uow.sessions.account_for(token_hash=digest, now=now)
            if account is None:
                raise AuthenticationFailed
            return account

    def logout(self, token: str) -> None:
        digest = token_digest(token, self._session_secret)
        with self._uow_factory() as uow:
            uow.sessions.revoke(digest)
            uow.commit()

    def list_users(self, *, page: int, page_size: int) -> tuple[list[AccountView], int]:
        with self._uow_factory() as uow:
            return uow.accounts.list_users(
                offset=(page - 1) * page_size,
                limit=page_size,
            )

    def create_user(
        self,
        *,
        email: str,
        display_name: str,
        password: str,
        role: str,
        locale: str,
        scopes: frozenset[AccessScope] | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] = (),
    ) -> AccountView:
        if role not in {"admin", "member"}:
            raise ValueError("invalid role")
        normalized_email = User.normalize_email(email)
        normalized_name = User.normalize_display_name(display_name)
        password_hash = self._password_hasher.hash(password)
        resolved_scopes = ALL_SCOPES if role == "admin" else (scopes or MEMBER_SCOPES)
        with self._uow_factory() as uow:
            if uow.accounts.email_in_use(normalized_email):
                raise AccountConflict
            account = uow.accounts.add_user(
                email=normalized_email,
                display_name=normalized_name,
                password_hash=password_hash,
                role=role,
                locale=locale,
                scopes=resolved_scopes,
                monitor_folder_ids=monitor_folder_ids,
            )
            uow.commit()
            return account

    def update_account(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None = None,
        display_name: str | None = None,
        password: str | None = None,
        current_password: str | None = None,
        locale: str | None = None,
    ) -> AccountView:
        normalized_email = User.normalize_email(email) if email is not None else None
        normalized_name = (
            User.normalize_display_name(display_name) if display_name is not None else None
        )
        password_hash = self._password_hasher.hash(password) if password else None
        with self._uow_factory() as uow:
            if normalized_email is not None or password_hash is not None:
                existing_password_hash = uow.accounts.password_hash_for(user_id)
                if (
                    current_password is None
                    or existing_password_hash is None
                    or not self._password_hasher.verify(
                        current_password,
                        existing_password_hash,
                    )
                ):
                    raise AuthenticationFailed
            if normalized_email is not None and uow.accounts.email_in_use(
                normalized_email,
                excluding=user_id,
            ):
                raise AccountConflict
            account = uow.accounts.update_user(
                user_id,
                email=normalized_email,
                display_name=normalized_name,
                password_hash=password_hash,
                locale=locale,
            )
            if account is None:
                raise AccountNotFound
            if password_hash is not None:
                uow.sessions.revoke_user(user_id)
            uow.commit()
            return account

    def update_managed_user(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None,
        display_name: str | None,
        role: str | None,
        disabled: bool | None,
        locale: str | None,
        scopes: frozenset[AccessScope] | None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None,
    ) -> AccountView:
        if role is not None and role not in {"admin", "member"}:
            raise ValueError("invalid role")
        normalized_email = User.normalize_email(email) if email is not None else None
        normalized_name = (
            User.normalize_display_name(display_name) if display_name is not None else None
        )
        with self._uow_factory() as uow:
            if normalized_email is not None and uow.accounts.email_in_use(
                normalized_email,
                excluding=user_id,
            ):
                raise AccountConflict
            resolved_scopes = ALL_SCOPES if role == "admin" else scopes
            account = uow.accounts.update_user(
                user_id,
                email=normalized_email,
                display_name=normalized_name,
                locale=locale,
                role=role,
                scopes=resolved_scopes,
                disabled=disabled,
                monitor_folder_ids=monitor_folder_ids,
                include_disabled=True,
            )
            if account is None:
                raise AccountNotFound
            if disabled or role is not None or scopes is not None:
                uow.sessions.revoke_user(user_id)
            uow.commit()
            return account

    def set_managed_password(self, user_id: uuid.UUID, password: str) -> AccountView:
        password_hash = self._password_hasher.hash(password)
        with self._uow_factory() as uow:
            account = uow.accounts.update_user(
                user_id,
                password_hash=password_hash,
                include_disabled=True,
            )
            if account is None:
                raise AccountNotFound
            uow.sessions.revoke_user(user_id)
            uow.commit()
            return account

    def request_password_reset(self, *, email: str, app_base_url: str) -> Path:
        normalized_email = User.normalize_email(email)
        now = datetime.now(UTC)
        with self._uow_factory() as uow:
            account = uow.accounts.get_user_by_email(normalized_email)
            if account is None:
                return self._password_reset_notice.path
            token = new_session_token()
            uow.password_resets.issue(
                user_id=account.id,
                token_hash=token_digest(token, self._session_secret),
                expires_at=now + self._password_reset_ttl,
                created_at=now,
            )
            reset_url = f"{app_base_url.rstrip('/')}/reset-password#token={quote(token, safe='')}"
            path = self._password_reset_notice.write(
                reset_url=reset_url,
                locale=account.locale,
            )
            try:
                uow.commit()
            except Exception:
                self._password_reset_notice.clear()
                raise
            return path

    def confirm_password_reset(self, *, token: str, new_password: str) -> None:
        now = datetime.now(UTC)
        digest = token_digest(token, self._session_secret)
        password_hash = self._password_hasher.hash(new_password)
        with self._uow_factory() as uow:
            user_id = uow.password_resets.consume(token_hash=digest, now=now)
            if user_id is None:
                raise InvalidResetToken
            account = uow.accounts.update_user(user_id, password_hash=password_hash)
            if account is None:
                raise InvalidResetToken
            uow.sessions.revoke_user(user_id)
            uow.commit()
        self._password_reset_notice.clear()

    def delete_user(self, user_id: uuid.UUID) -> None:
        with self._uow_factory() as uow:
            if not uow.accounts.delete_user(user_id):
                raise AccountNotFound
            uow.commit()

    def preferences(self, user_id: uuid.UUID) -> dict[str, object]:
        with self._uow_factory() as uow:
            return uow.accounts.preferences(user_id)

    def save_preferences(
        self,
        user_id: uuid.UUID,
        values: dict[str, object],
    ) -> dict[str, object]:
        with self._uow_factory() as uow:
            saved = uow.accounts.save_preferences(user_id, values)
            uow.commit()
            return saved

    def _create_grant(self, uow: AccountsUnitOfWork, account: AccountView) -> SessionGrant:
        token = new_session_token()
        expires_at = datetime.now(UTC) + self._session_ttl
        uow.sessions.add(
            user_id=account.id,
            token_hash=token_digest(token, self._session_secret),
            expires_at=expires_at,
        )
        return SessionGrant(token=token, expires_at=expires_at, account=account)
