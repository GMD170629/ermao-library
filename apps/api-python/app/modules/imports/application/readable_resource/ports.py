"""Application ports for the ADR 0018 readable-resource pipeline."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeTerminationReason,
)
from app.modules.imports.domain.import_run_policies import (
    ImportRunKind,
    ImportRunState,
    LibraryImportTaskState,
)
from app.modules.imports.domain.resource_adapters import ResourceAdapterSpec
from app.modules.library.public import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)

__all__ = [
    "AdapterIdentity",
    "AssetTechnicalMetadata",
    "BookResourceRepositoryPort",
    "ClaimedWork",
    "ClockPort",
    "DirectoryEntry",
    "FileParseResult",
    "ImportRunRecord",
    "ImportRunRepositoryPort",
    "InterpretationRecord",
    "LibraryConfigPort",
    "LibraryImportTaskRecord",
    "LibrarySourceTreeConfig",
    "ObservedSourceEntry",
    "ParsedAssetPayload",
    "PipelineLogPort",
    "ReadableResourceRecord",
    "ResourceAdapterExecutorPort",
    "ResourceAdapterSpec",
    "ResourceCandidateRecord",
    "SidecarWritebackPort",
    "SourceNodeRecord",
    "SourceNodeRepositoryPort",
    "SourceTreeFilesystemPort",
    "UnitOfWorkPort",
    "WorkQueuePort",
    "adapter_identity",
]


def adapter_identity(spec: ResourceAdapterSpec) -> AdapterIdentity:
    return AdapterIdentity(
        adapter_id=spec.adapter_id.value,
        adapter_version=spec.adapter_version,
        media_kind=spec.media_kind,
        format_label=spec.format_label,
    )


@dataclass(frozen=True, slots=True)
class ClaimedWork:
    work_item_id: str
    work_kind: Literal["scan", "import"]
    target_id: str
    lease_owner: str
    lease_expires_at: datetime
    scan_job_id: str | None
    bridge_import_task_id: str | None


@dataclass(frozen=True, slots=True)
class LibraryImportTaskRecord:
    id: str
    library_id: str
    state: LibraryImportTaskState
    resource_id: str
    source_node_id: str
    owner_import_run_id: str | None
    role: AssetRole
    attempt_count: int


@dataclass(frozen=True, slots=True)
class ImportRunRecord:
    id: str
    library_id: str
    kind: ImportRunKind
    state: ImportRunState
    source_node_id: str
    resource_id: str | None
    adapter_id: str | None
    adapter_version: str | None
    discovery_complete: bool


@dataclass(frozen=True, slots=True)
class ResourceCandidateRecord:
    import_run_id: str
    library_id: str
    book_id: str | None
    source_node_id: str
    adapter_id: str
    adapter_version: str
    media_kind: str
    format_label: str
    title: str | None


@dataclass(frozen=True, slots=True)
class AssetCandidateRecord:
    import_run_id: str
    library_id: str
    source_node_id: str
    role: AssetRole
    import_state: AssetImportState
    sequence_index: int | None
    sort_key: str | None
    failure_reason: str | None


@dataclass(frozen=True, slots=True)
class AssetTechnicalMetadata:
    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    disc_number: int | None = None
    track_number: int | None = None


@dataclass(frozen=True, slots=True)
class ParsedAssetPayload:
    title: str | None
    role: AssetRole
    sequence_index: int | None
    sort_key: str | None
    mime_type: str | None
    duration_ms: int | None
    failure_reason: str | None
    technical: AssetTechnicalMetadata


@dataclass(frozen=True, slots=True)
class FileParseResult:
    ok: bool
    adapter: ResourceAdapterSpec
    resource_title: str | None
    asset: ParsedAssetPayload | None
    error_code: str | None
    error_summary: str | None


DirectoryEntry = tuple[str, SourceNodePhysicalKind, int | None, int]


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class UnitOfWorkPort(Protocol):
    def release_before_io(self) -> None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def rollback(self) -> None: ...


class SourceTreeFilesystemPort(Protocol):
    def resolve_under_root(self, root: Path, relative_path: str) -> Path: ...

    def iter_directory_entries(
        self,
        absolute_directory: Path,
    ) -> Iterator[DirectoryEntry]: ...

    def probe_directory(
        self,
        *,
        root: Path,
        directory_relative_path: str,
        ignore_hidden: bool,
        ignore_patterns: str | None,
        global_ignore_patterns: str,
        sample_limit: int,
        max_entries: int,
        max_depth: int,
        time_budget_ms: int,
    ) -> tuple[DirectoryProbeDecision, ProbeTerminationReason]: ...

    def path_is_readable_directory(self, path: Path) -> bool: ...


class ImportRunRepositoryPort(Protocol):
    def create_run(
        self,
        *,
        library_id: str,
        kind: ImportRunKind,
        source_node_id: str,
        resource_id: str | None,
        adapter_id: str | None,
        adapter_version: str | None,
    ) -> str: ...

    def get_run(self, run_id: str) -> ImportRunRecord | None: ...

    def get_resource_candidate(
        self, run_id: str
    ) -> ResourceCandidateRecord | None: ...

    def mark_discovery_complete(self, run_id: str) -> None: ...

    def is_discovery_complete(self, run_id: str) -> bool: ...

    def set_run_state(
        self,
        run_id: str,
        state: ImportRunState,
        *,
        error_summary: str | None = None,
        published_at: datetime | None = None,
    ) -> None: ...

    def attach_resource(self, run_id: str, resource_id: str) -> None: ...

    def upsert_resource_candidate(
        self,
        *,
        import_run_id: str,
        library_id: str,
        book_id: str | None,
        source_node_id: str,
        adapter: ResourceAdapterSpec,
        title: str | None,
    ) -> None: ...

    def upsert_asset_candidate(
        self,
        *,
        import_run_id: str,
        library_id: str,
        source_node_id: str,
        role: AssetRole,
        import_state: AssetImportState,
        sequence_index: int | None,
        sort_key: str | None,
        failure_reason: str | None,
    ) -> None: ...

    def count_ready_asset_candidates(self, import_run_id: str) -> int: ...

    def list_ready_asset_candidates(
        self, import_run_id: str
    ) -> tuple[AssetCandidateRecord, ...]: ...

    def count_incomplete_tasks(self, owner_import_run_id: str) -> int: ...

    def count_failed_tasks(self, owner_import_run_id: str) -> int: ...

    def create_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        owner_import_run_id: str | None,
        role: AssetRole,
    ) -> LibraryImportTaskRecord: ...

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None: ...

    def mark_task_state(
        self,
        task_id: str,
        state: LibraryImportTaskState,
        *,
        error_summary: str | None = None,
        increment_attempt: bool = False,
    ) -> None: ...

    def cleanup_run_candidates(self, run_id: str) -> None: ...


class WorkQueuePort(Protocol):
    def queued_item_count(self) -> int: ...

    def enqueue_library_import_task(self, task_id: str) -> None: ...

    def enqueue_library_scan(self, library_id: str) -> None: ...

    def claim_next(self, worker_id: str, *, lease_seconds: int) -> ClaimedWork | None: ...

    def complete(self, claim: ClaimedWork) -> bool: ...

    def heartbeat(self, claim: ClaimedWork) -> bool: ...

    def is_claim_valid(self, claim: ClaimedWork) -> bool: ...

    def fence_claim(self, claim: ClaimedWork, *, lease_seconds: int) -> bool: ...

    def release_and_requeue(
        self, claim: ClaimedWork, *, delay_seconds: int = 5
    ) -> bool: ...


class ResourceAdapterExecutorPort(Protocol):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
    ) -> FileParseResult: ...


class PipelineLogPort(Protocol):
    def emit(
        self,
        event: str,
        *,
        library_id: str | None = None,
        resource_id: str | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        outcome: str | None = None,
    ) -> None: ...


class SidecarWritebackPort(Protocol):
    def schedule_after_commit(self, resource_id: str) -> None: ...
