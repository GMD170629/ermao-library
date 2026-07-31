"""Explicit DTOs for the persistent import scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

ImportWorkKind = Literal["SCAN_DIRECTORY", "IMPORT_SOURCE"]
ImportWorkStatus = Literal["PENDING", "LEASED"]
ImportScanStatus = Literal["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"]


@dataclass(frozen=True)
class ScanErrorDTO:
    path: str
    error: str
    code: str | None = None
    limit: int | None = None
    observed_count: int | None = None

    def to_storage(self) -> dict[str, object]:
        values: dict[str, object] = {
            "path": self.path,
            "error": self.error,
        }
        if self.code is not None:
            values["code"] = self.code
        if self.limit is not None:
            values["limit"] = self.limit
        if self.observed_count is not None:
            values["observedCount"] = self.observed_count
        return values


@dataclass(frozen=True)
class ImportWorkItemDTO:
    id: str
    kind: ImportWorkKind
    scan_job_id: str | None
    import_task_id: str | None
    status: ImportWorkStatus
    attempts: int


@dataclass(frozen=True)
class ImportScanJobDTO:
    id: str
    monitor_folder_id: str | None
    actor_user_id: str | None
    root_path: str
    trigger: str
    status: ImportScanStatus
    directories_scanned: int
    files_scanned: int
    candidates_found: int
    queued_count: int
    skipped_count: int
    error_count: int
    ignored_reason_counts: dict[str, int]
    error_samples: tuple[ScanErrorDTO, ...]
    restart_count: int
    started_at: datetime | None
    heartbeat_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ScanBatchResult:
    queued_count: int
    cached_count: int
