from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class HealthStatus:
    name: str
    status: str
    checked_at: datetime
    detail: dict[str, object]


class HealthContributor(Protocol):
    name: str

    def check(self) -> HealthStatus: ...


@dataclass(frozen=True, slots=True)
class BackupManifest:
    app_version: str
    postgres_major: int
    alembic_revision: str
    checksum: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EventView:
    id: uuid.UUID
    actor_id: uuid.UUID | None
    kind: str
    severity: str
    message_key: str
    params: dict[str, object]
    trace_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SettingView:
    key: str
    value: dict[str, object]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LogStorageView:
    size_bytes: int
    max_bytes: int
    last_pruned_at: datetime | None


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    name: str
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class QueueView:
    name: str
    enabled: bool
    status: str
    counts: dict[str, int]


class QueueOverviewPort(Protocol):
    def snapshots(self) -> tuple[QueueSnapshot, ...]: ...


@dataclass(frozen=True, slots=True)
class BackupView:
    id: uuid.UUID
    status: str
    archive_name: str
    app_version: str
    postgres_major: int
    alembic_revision: str
    checksum: str | None
    size_bytes: int | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class BackupArchive:
    body: Iterable[bytes]
    filename: str
    size_bytes: int
    checksum: str


class OperationsRepository(Protocol):
    def list_settings(self) -> list[SettingView]: ...

    def save_settings(
        self, values: dict[str, dict[str, object]], actor_id: uuid.UUID
    ) -> list[SettingView]: ...

    def append_event(
        self,
        *,
        actor_id: uuid.UUID | None,
        kind: str,
        severity: str,
        message_key: str,
        params: dict[str, object],
        trace_id: str | None,
        now: datetime,
    ) -> None: ...

    def list_events(
        self,
        *,
        offset: int,
        limit: int,
        kind: str | None,
        source: str | None,
        severity: str | None,
        search: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> tuple[list[EventView], int]: ...

    def clear_events(self) -> int: ...

    def event_storage_size(self) -> int: ...

    def prune_events(self, max_bytes: int) -> int: ...

    def request_backup(
        self,
        *,
        requested_by: uuid.UUID,
        archive_name: str,
        app_version: str,
        postgres_major: int,
        alembic_revision: str,
    ) -> BackupView: ...

    def list_backups(self) -> list[BackupView]: ...

    def get_backup(self, backup_id: uuid.UUID) -> BackupView | None: ...

    def delete_backup(self, backup_id: uuid.UUID) -> BackupView | None: ...

    def claim_backup(self) -> BackupView | None: ...

    def complete_backup(self, backup_id: uuid.UUID, *, checksum: str, size_bytes: int) -> None: ...

    def fail_backup(self, backup_id: uuid.UUID, detail: str) -> None: ...

    def mark_restoring(self, backup_id: uuid.UUID) -> BackupView | None: ...

    def complete_restore(self, backup_id: uuid.UUID) -> None: ...


class OperationsUnitOfWork(UnitOfWork, Protocol):
    operations: OperationsRepository


class BackupExecutorPort(Protocol):
    def create(self, backup: BackupView) -> tuple[str, int]: ...

    def delete(self, backup: BackupView) -> None: ...

    def open(self, backup: BackupView) -> BackupArchive: ...


class RestoreControlPort(Protocol):
    def request(self, backup: BackupView, requested_by: uuid.UUID) -> str: ...

    def status(self, request_id: str) -> RestoreStatusView | None: ...


@dataclass(frozen=True, slots=True)
class RestoreStatusView:
    request_id: str
    backup_id: uuid.UUID
    status: str
    detail: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RestoreRequest:
    request_id: str
    backup_id: uuid.UUID
    archive: str
    checksum: str
    app_version: str
    postgres_major: int
    alembic_revision: str


class RestoreControlInboxPort(Protocol):
    def next_request(self) -> RestoreRequest | None: ...

    def complete(self, request: RestoreRequest) -> None: ...

    def fail(self, request: RestoreRequest, detail: str) -> None: ...


class RestoreExecutorPort(Protocol):
    def execute(self, request: RestoreRequest) -> None: ...
