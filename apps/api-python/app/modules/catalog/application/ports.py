"""Application ports for Library commands and queries.

Concrete SQLAlchemy and filesystem adapters are intentionally outside this
module.  These protocols are the only dependency surface used by use cases.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Literal, Protocol, Self

from app.modules.catalog.application.dto import (
    IgnoreRulesResult,
    LibraryGrantPage,
    LibraryPage,
)
from app.modules.catalog.domain.access import LibraryGrant
from app.modules.catalog.domain.ignore_rules import IgnoreRule
from app.modules.catalog.domain.library import Library
from app.modules.catalog.domain.model import PathComparison
from app.modules.catalog.domain.root_paths import RootClaim, RootObservation

EventValue = str | int | bool
EventPayload = tuple[tuple[str, EventValue], ...]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_type: str
    actor_id: str
    library_id: str | None
    payload: EventPayload = ()


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_type: str
    aggregate_id: str
    actor_id: str
    payload: EventPayload = ()


@dataclass(frozen=True, slots=True)
class ReservedRoot:
    library_id: str
    claim: RootClaim


@dataclass(frozen=True, slots=True)
class VisibleLibrary:
    library: Library
    grant: LibraryGrant


@dataclass(frozen=True, slots=True)
class LibraryPageQuery:
    actor_id: str
    cursor: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class LibraryGrantPageQuery:
    actor_id: str
    library_id: str
    cursor: str | None = None
    limit: int = 50


class LibraryRootPreflight(Protocol):
    def preflight(
        self, requested_path: str, *, path_comparison: PathComparison
    ) -> RootObservation: ...

    def revalidate(
        self,
        requested_path: str,
        observation: RootObservation,
        *,
        path_comparison: PathComparison,
    ) -> RootObservation: ...


class RootRegistryLease(AbstractContextManager["RootRegistryLease"], Protocol):
    fence: int

    def heartbeat(self) -> None: ...


class RootRegistry(Protocol):
    def acquire(self, *, owner_token: str) -> RootRegistryLease: ...

    def reserved_roots(self) -> tuple[ReservedRoot, ...]: ...


class LibraryRepository(Protocol):
    def insert(self, library: Library) -> None: ...

    def get_for_update(self, library_id: str) -> Library | None: ...

    def update_if_revision(
        self, library: Library, *, expected_config_revision: int
    ) -> bool: ...


class LibraryGrantRepository(Protocol):
    def get(self, user_id: str, library_id: str) -> LibraryGrant | None: ...

    def save_preserving_last_admin(self, grant: LibraryGrant) -> bool: ...

    def delete_preserving_last_admin(self, user_id: str, library_id: str) -> bool: ...


class IgnoreRuleRepository(Protocol):
    def replace(
        self,
        library_id: str,
        rules: tuple[IgnoreRule, ...],
        *,
        expected_config_revision: int,
        next_config_revision: int,
    ) -> None: ...


class LibraryQueryRepository(Protocol):
    def list_visible(self, query: LibraryPageQuery) -> LibraryPage: ...

    # Ordinary reads exclude REMOVING libraries for every grant level.
    def get_visible(self, actor_id: str, library_id: str) -> VisibleLibrary | None: ...

    # Management reads may retain an ADMIN-only view while removal is in progress.
    def get_manageable(
        self, actor_id: str, library_id: str
    ) -> VisibleLibrary | None: ...

    def list_grants(self, query: LibraryGrantPageQuery) -> LibraryGrantPage: ...

    def get_ignore_rules(
        self, actor_id: str, library_id: str
    ) -> IgnoreRulesResult | None: ...


class UserAuthorizationPort(Protocol):
    def ensure_can_create_library(self, user_id: str) -> None: ...

    def ensure_active_user(self, user_id: str) -> None: ...

    def increment_authz_version(self, user_id: str) -> None: ...


class LibraryWritePolicyPort(Protocol):
    """Validate that a READ_WRITE -> READ_ONLY transition is safe."""

    def ensure_read_only_safe(self, library_id: str) -> None: ...


class SystemCreateLibraryPolicy(Protocol):
    def authorize(self, actor_id: str) -> None: ...


class ScopeEpochGenerator(Protocol):
    def next_scope_epoch(self) -> int: ...


class IdGenerator(Protocol):
    def new_id(self) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class AuditPort(Protocol):
    def append(self, event: AuditEvent) -> None: ...


class OutboxPort(Protocol):
    def append(self, event: OutboxEvent) -> None: ...


class LibraryUnitOfWork(Protocol):
    libraries: LibraryRepository
    grants: LibraryGrantRepository
    ignore_rules: IgnoreRuleRepository
    users: UserAuthorizationPort
    queries: LibraryQueryRepository
    audit: AuditPort
    outbox: OutboxPort
    write_policy: LibraryWritePolicyPort

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class LibraryUowFactory(Protocol):
    def __call__(self) -> LibraryUnitOfWork: ...
