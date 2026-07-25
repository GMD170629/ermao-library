from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO, Protocol

from appv2.platform.database.contracts import UnitOfWork


@dataclass(frozen=True, slots=True)
class ImportRequest:
    source_path: str
    requested_by: uuid.UUID
    idempotency_key: str
    move_source: bool = False


@dataclass(frozen=True, slots=True)
class ImportResult:
    job_id: uuid.UUID
    status: str
    edition_id: uuid.UUID | None
    duplicate: bool


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: uuid.UUID
    kind: str
    status: str
    source_path: str
    attempt: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    result_id: uuid.UUID | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class ImportQueuePort(Protocol):
    def enqueue(self, request: ImportRequest) -> ImportResult: ...


@dataclass(frozen=True, slots=True)
class MonitorFolder:
    id: uuid.UUID
    path: str
    enabled: bool
    recursive: bool
    move_source: bool
    options: dict[str, object]
    last_scan_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DirectoryNode:
    name: str
    path: str
    readable: bool
    children: tuple[DirectoryNode, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PreparedImport:
    title: str
    author: str | None
    media_type: str
    format: str
    source_path: str
    original_name: str
    size_bytes: int
    checksum: str
    metadata: dict[str, object]


class IngestionRepository(Protocol):
    def enqueue(self, request: ImportRequest, *, kind: str = "import") -> ImportResult: ...

    def list_jobs(
        self, *, offset: int, limit: int, status: str | None
    ) -> tuple[list[IngestionJob], int]: ...

    def get_job(self, job_id: uuid.UUID) -> IngestionJob | None: ...

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> IngestionJob | None: ...

    def complete(self, job_id: uuid.UUID, edition_id: uuid.UUID) -> None: ...

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retry_at: datetime | None,
    ) -> None: ...

    def cancel(self, job_id: uuid.UUID) -> bool: ...

    def delete_job(self, job_id: uuid.UUID) -> bool: ...

    def clear_finished(self) -> int: ...

    def retry(self, job_id: uuid.UUID, now: datetime) -> bool: ...

    def list_folders(self) -> list[MonitorFolder]: ...

    def get_folder(self, folder_id: uuid.UUID) -> MonitorFolder | None: ...

    def add_folder(
        self,
        *,
        path: str,
        recursive: bool,
        move_source: bool,
        options: dict[str, object],
    ) -> MonitorFolder: ...

    def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        enabled: bool | None,
        recursive: bool | None,
        move_source: bool | None,
        options: dict[str, object] | None,
        scanned_at: datetime | None,
    ) -> MonitorFolder | None: ...

    def delete_folder(self, folder_id: uuid.UUID) -> bool: ...


class IngestionUnitOfWork(UnitOfWork, Protocol):
    ingestion: IngestionRepository


class FileDiscoveryPort(Protocol):
    def validate_folder(self, path: str) -> str: ...

    def discover(self, path: str, *, recursive: bool) -> list[str]: ...

    def tree(self, path: str | None = None) -> tuple[DirectoryNode, str]: ...


class UploadStoragePort(Protocol):
    def store(self, name: str, stream: BinaryIO) -> str: ...


class ImportPreparationPort(Protocol):
    def prepare(self, source_path: str) -> PreparedImport: ...
