from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
    ) -> AccountView: ...

    def update_user(
        self,
        user_id: uuid.UUID,
        *,
        email: str | None = None,
        display_name: str | None = None,
        password_hash: str | None = None,
        locale: str | None = None,
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


class AccountsUnitOfWork(UnitOfWork, Protocol):
    accounts: AccountsRepository
    sessions: SessionsRepository


CurrentAccount = Callable[..., AccountView]
