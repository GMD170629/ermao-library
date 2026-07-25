from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from appv2.platform.database.contracts import UnitOfWork


class AccessScope(StrEnum):
    CATALOG_READ = "catalog:read"
    CATALOG_WRITE = "catalog:write"
    INGESTION_WRITE = "ingestion:write"
    METADATA_WRITE = "metadata:write"
    READING_WRITE = "reading:write"
    DISCOVERY_WRITE = "discovery:write"
    DELIVERY_WRITE = "delivery:write"
    OPERATIONS_READ = "operations:read"
    OPERATIONS_WRITE = "operations:write"
    USERS_WRITE = "users:write"


ALL_SCOPES = frozenset(AccessScope)
MEMBER_SCOPES = frozenset(
    {
        AccessScope.CATALOG_READ,
        AccessScope.READING_WRITE,
        AccessScope.DISCOVERY_WRITE,
        AccessScope.DELIVERY_WRITE,
    }
)


@dataclass(frozen=True, slots=True)
class AccountView:
    id: uuid.UUID
    email: str
    display_name: str
    role: str
    locale: str
    scopes: frozenset[AccessScope]
    disabled: bool
    monitor_folder_ids: tuple[uuid.UUID, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionGrant:
    token: str
    expires_at: datetime
    account: AccountView


class AccountsRepository(Protocol):
    def count_users(self) -> int: ...

    def get_user(self, user_id: uuid.UUID) -> AccountView | None: ...

    def get_user_by_email(self, email: str) -> AccountView | None: ...

    def email_in_use(self, email: str, *, excluding: uuid.UUID | None = None) -> bool: ...

    def password_hash_for(self, user_id: uuid.UUID) -> str | None: ...

    def add_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        role: str,
        locale: str,
        scopes: frozenset[AccessScope],
        monitor_folder_ids: tuple[uuid.UUID, ...] = (),
    ) -> AccountView: ...

    def update_user(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None = None,
        display_name: str | None = None,
        password_hash: str | None = None,
        locale: str | None = None,
        role: str | None = None,
        scopes: frozenset[AccessScope] | None = None,
        disabled: bool | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None = None,
    ) -> AccountView | None: ...

    def list_users(self, *, offset: int, limit: int) -> tuple[list[AccountView], int]: ...

    def delete_user(self, user_id: uuid.UUID) -> bool: ...

    def preferences(self, user_id: uuid.UUID) -> dict[str, object]: ...

    def save_preferences(
        self,
        user_id: uuid.UUID,
        values: dict[str, object],
    ) -> dict[str, object]: ...


class SessionsRepository(Protocol):
    def add(self, *, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None: ...

    def account_for(self, *, token_hash: str, now: datetime) -> AccountView | None: ...

    def revoke(self, token_hash: str) -> bool: ...

    def revoke_user(self, user_id: uuid.UUID) -> None: ...


class PasswordResetsRepository(Protocol):
    def issue(
        self,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime,
    ) -> None: ...

    def consume(self, *, token_hash: str, now: datetime) -> uuid.UUID | None: ...


class PasswordResetNoticePort(Protocol):
    @property
    def path(self) -> Path: ...

    def write(self, *, reset_url: str, locale: str) -> Path: ...

    def clear(self) -> None: ...


class AccountsUnitOfWork(UnitOfWork, Protocol):
    accounts: AccountsRepository
    sessions: SessionsRepository
    password_resets: PasswordResetsRepository


CurrentAccount = Callable[..., AccountView]
