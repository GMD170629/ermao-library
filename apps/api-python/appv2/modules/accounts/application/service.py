from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from appv2.modules.accounts.contracts import (
    ALL_SCOPES,
    MEMBER_SCOPES,
    AccountsUnitOfWork,
    AccountView,
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


class AccountService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AccountsUnitOfWork],
        password_hasher: PasswordHasher,
        session_secret: str,
        session_ttl_seconds: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._password_hasher = password_hasher
        self._session_secret = session_secret
        self._session_ttl = timedelta(seconds=session_ttl_seconds)

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
    ) -> AccountView:
        if role not in {"admin", "member"}:
            raise ValueError("invalid role")
        normalized_email = User.normalize_email(email)
        normalized_name = User.normalize_display_name(display_name)
        password_hash = self._password_hasher.hash(password)
        scopes = ALL_SCOPES if role == "admin" else MEMBER_SCOPES
        with self._uow_factory() as uow:
            if uow.accounts.get_user_by_email(normalized_email) is not None:
                raise AccountConflict
            account = uow.accounts.add_user(
                email=normalized_email,
                display_name=normalized_name,
                password_hash=password_hash,
                role=role,
                locale=locale,
                scopes=scopes,
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
            if normalized_email is not None:
                existing = uow.accounts.get_user_by_email(normalized_email)
                if existing is not None and existing.id != user_id:
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
