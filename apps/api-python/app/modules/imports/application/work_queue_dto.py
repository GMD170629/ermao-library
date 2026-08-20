"""Explicit DTOs for the persistent import scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
    library_id: str | None
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
    rejected_count: int = 0
    errors: tuple[ScanErrorDTO, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedTopologySource:
    source_path: Path
    source_key: str
    work_source_key: str
    work_title: str
    version_source_key: str
    version_name: str | None
    volume_resource_key: str
    volume_title: str
    volume_sort_order: int
    volume_format: str
    asset_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class PreparedScanSources:
    topology_sources: tuple[PreparedTopologySource, ...]
    source_pairs: tuple[tuple[str, str], ...]
    candidate_count: int
    rejected_count: int = 0
    errors: tuple[ScanErrorDTO, ...] = ()


@dataclass(frozen=True, slots=True)
class ScanCandidateProjection:
    task_sources: tuple[tuple[str | None, str, str], ...]
    library_sources: tuple[tuple[str | None, str], ...]
    topology_works: tuple[tuple[str, str], ...]
    topology_versions: tuple[tuple[str, str, str], ...]
    topology_volumes: tuple[tuple[str, str, str, str], ...]
    media_kind_policy: str


@dataclass(frozen=True, slots=True)
class PreparedScanCandidateBatch:
    topology_work_rows: tuple[dict[str, object], ...]
    topology_version_rows: tuple[dict[str, object], ...]
    topology_volume_rows: tuple[dict[str, object], ...]
    task_rows: tuple[dict[str, object], ...]
    asset_rows: tuple[dict[str, object], ...]
    work_rows: tuple[dict[str, object], ...]
    result: ScanBatchResult


@dataclass(frozen=True, slots=True)
class ImportQueueMaintenanceProjection:
    task_rows: tuple[tuple[str, str | None, str, str], ...]
    file_rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PreparedImportQueueMaintenance:
    task_updates: tuple[dict[str, object], ...]
    work_rows: tuple[dict[str, object], ...]
    file_updates: tuple[dict[str, object], ...]

    @property
    def changed_count(self) -> int:
        return len(self.task_updates) + len(self.file_updates)
