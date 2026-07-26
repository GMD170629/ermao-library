from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import BinaryIO, Protocol

from appv2.modules.catalog.contracts import PreparedPublication
from appv2.platform.database.contracts import UnitOfWork

SUPPORTED_IMPORT_EXTENSIONS = (
    ".epub",
    ".pdf",
    ".cbz",
    ".zip",
    ".txt",
    ".fb2",
    ".mobi",
    ".azw",
    ".azw3",
    ".prc",
    ".mp3",
    ".m4a",
    ".m4b",
)


@dataclass(frozen=True, slots=True)
class ImportRequest:
    source_path: str
    requested_by: uuid.UUID | None
    idempotency_key: str
    origin: str = "manual"
    monitor_folder_id: uuid.UUID | None = None
    triggered_by: str = "user"
    options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ImportResult:
    job_id: uuid.UUID
    status: str
    work_id: uuid.UUID | None
    edition_id: uuid.UUID | None
    volume_ids: tuple[uuid.UUID, ...]
    duplicate: bool


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: uuid.UUID
    kind: str
    origin: str
    status: str
    stage: str
    progress: int
    source_path: str
    requested_by: uuid.UUID | None
    monitor_folder_id: uuid.UUID | None
    triggered_by: str
    options: dict[str, object]
    attempt: int
    max_attempts: int
    next_attempt_at: datetime
    lease_expires_at: datetime | None
    cancel_requested: bool
    result_work_id: uuid.UUID | None
    result_edition_id: uuid.UUID | None
    result_volume_ids: tuple[uuid.UUID, ...]
    retryable: bool
    error_code: str | None
    error_detail: str | None
    started_at: datetime | None
    finished_at: datetime | None
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
    options: dict[str, object]
    last_scan_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class JobLog:
    id: uuid.UUID
    job_id: uuid.UUID
    level: str
    message_key: str
    params: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ScanRun:
    id: uuid.UUID
    trigger: str
    status: str
    monitor_folder_id: uuid.UUID | None
    requested_by: uuid.UUID | None
    directories_scanned: int
    files_scanned: int
    candidates_found: int
    queued: int
    ignored: int
    errors: tuple[dict[str, str], ...]
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    id: uuid.UUID
    allowed_extensions: tuple[str, ...]
    ignore_patterns: tuple[str, ...]
    stability_check_enabled: bool
    stability_check_seconds: int
    auto_convert_to_epub: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IngestionOutboxEvent:
    id: uuid.UUID
    event_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, object]
    attempt: int


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
    file_media_type: str
    format: str
    source_path: str
    original_name: str
    size_bytes: int
    checksum: str
    metadata: dict[str, object]


class IngestionRepository(Protocol):
    def enqueue(self, request: ImportRequest, *, kind: str = "import") -> ImportResult: ...

    def list_jobs(
        self,
        *,
        offset: int,
        limit: int,
        status: str | None,
        kind: str | None,
        origin: str | None = None,
        keyword: str | None = None,
        monitor_folder_ids: tuple[uuid.UUID, ...] | None = None,
        requested_by: uuid.UUID | None = None,
    ) -> tuple[list[IngestionJob], int]: ...

    def queue_counts(self) -> dict[str, int]: ...

    def get_job(self, job_id: uuid.UUID) -> IngestionJob | None: ...

    def claim_next(
        self, *, worker_id: str, now: datetime, lease_until: datetime
    ) -> IngestionJob | None: ...

    def renew_lease(self, job_id: uuid.UUID, *, worker_id: str, lease_until: datetime) -> bool: ...

    def update_progress(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        stage: str,
        progress: int,
        message_key: str,
        params: dict[str, object] | None = None,
    ) -> bool: ...

    def acknowledge_cancellation(self, job_id: uuid.UUID, *, worker_id: str) -> bool: ...

    def complete(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        work_id: uuid.UUID,
        edition_id: uuid.UUID,
        volume_ids: tuple[uuid.UUID, ...],
    ) -> bool: ...

    def fail(
        self,
        job_id: uuid.UUID,
        *,
        worker_id: str,
        error_code: str,
        error_detail: str,
        retryable: bool,
        retry_at: datetime | None,
    ) -> bool: ...

    def cancel(self, job_id: uuid.UUID) -> bool: ...

    def delete_job(self, job_id: uuid.UUID) -> bool: ...

    def clear_finished(self) -> int: ...

    def retry(self, job_id: uuid.UUID, now: datetime) -> bool: ...

    def list_logs(self, job_id: uuid.UUID, *, limit: int = 100) -> list[JobLog]: ...

    def get_policy(self) -> IngestionPolicy: ...

    def update_policy(
        self,
        *,
        allowed_extensions: tuple[str, ...],
        ignore_patterns: tuple[str, ...],
        stability_check_enabled: bool,
        stability_check_seconds: int,
        auto_convert_to_epub: bool,
    ) -> IngestionPolicy: ...

    def create_scan_run(
        self,
        *,
        trigger: str,
        monitor_folder_id: uuid.UUID | None,
        requested_by: uuid.UUID | None,
    ) -> ScanRun: ...

    def get_scan_run(self, scan_run_id: uuid.UUID) -> ScanRun | None: ...

    def claim_scan_run(
        self,
        *,
        now: datetime,
        recovery_before: datetime,
    ) -> ScanRun | None: ...

    def observe_and_enqueue(
        self,
        *,
        monitor_folder_id: uuid.UUID,
        normalized_path: str,
        request: ImportRequest,
        seen_at: datetime,
    ) -> ImportResult | None: ...

    def complete_scan_run(
        self,
        scan_run_id: uuid.UUID,
        *,
        directories_scanned: int,
        files_scanned: int,
        candidates_found: int,
        queued: int,
        ignored: int,
        errors: tuple[dict[str, str], ...],
        finished_at: datetime,
    ) -> bool: ...

    def fail_scan_run(
        self,
        scan_run_id: uuid.UUID,
        *,
        errors: tuple[dict[str, str], ...],
        finished_at: datetime,
    ) -> bool: ...

    def claim_outbox(
        self,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> IngestionOutboxEvent | None: ...

    def publish_outbox(self, event_id: uuid.UUID, *, published_at: datetime) -> bool: ...

    def fail_outbox(
        self,
        event_id: uuid.UUID,
        *,
        error_detail: str,
        retry_at: datetime,
    ) -> bool: ...

    def list_folders(self) -> list[MonitorFolder]: ...

    def get_folder(self, folder_id: uuid.UUID) -> MonitorFolder | None: ...

    def add_folder(
        self,
        *,
        path: str,
        recursive: bool,
        options: dict[str, object],
    ) -> MonitorFolder: ...

    def update_folder(
        self,
        folder_id: uuid.UUID,
        *,
        enabled: bool | None,
        recursive: bool | None,
        options: dict[str, object] | None,
        scanned_at: datetime | None,
    ) -> MonitorFolder | None: ...

    def delete_folder(self, folder_id: uuid.UUID) -> bool: ...


class IngestionUnitOfWork(UnitOfWork, Protocol):
    ingestion: IngestionRepository


class FileDiscoveryPort(Protocol):
    def validate_folder(self, path: str) -> str: ...

    def validate_source(self, path: str, *, allowed_roots: tuple[str, ...]) -> str: ...

    def discover(self, path: str, *, recursive: bool) -> list[str]: ...

    def discover_stable(
        self,
        path: str,
        *,
        recursive: bool,
        stability_seconds: float,
        options: dict[str, object],
    ) -> tuple[list[str], int]: ...

    def source_exists(self, path: str) -> bool: ...

    def tree(self, path: str | None = None) -> tuple[DirectoryNode, str]: ...


class UploadStoragePort(Protocol):
    def store(self, name: str, stream: BinaryIO) -> str: ...


class ImportPreparationPort(Protocol):
    def prepare(
        self,
        source_path: str,
        *,
        auto_convert_to_epub: bool,
    ) -> PreparedPublication: ...


class ConversionPreparationPort(Protocol):
    def prepare(
        self,
        source_path: str,
        *,
        identity: str,
        language: str | None,
    ) -> PreparedImport: ...
