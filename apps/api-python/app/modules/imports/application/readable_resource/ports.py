"""Application ports for the ADR 0018 readable-resource pipeline."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

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


@dataclass(frozen=True, slots=True)
class LibrarySourceTreeConfig:
    library_id: str
    root_path: Path
    organization_mode: TargetLibraryOrganizationMode
    ignore_hidden: bool
    ignore_patterns: str | None
    global_ignore_patterns: str
    min_file_size_bytes: int
    queue_high_water: int
    probe_sample_limit: int
    probe_max_entries: int
    probe_max_depth: int
    probe_time_budget_ms: int


@dataclass(frozen=True, slots=True)
class ObservedSourceEntry:
    relative_path: SourceNodeRelativePath
    physical_kind: SourceNodePhysicalKind
    observed_size_bytes: int | None
    observed_mtime_ns: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class SourceNodeRecord:
    id: str
    library_id: str
    parent_id: str | None
    relative_path: str
    path_key: str
    name: str
    physical_kind: SourceNodePhysicalKind
    observed_size_bytes: int | None
    observed_mtime_ns: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class InterpretationRecord:
    source_node_id: str
    result: str
    source: str
    adapter_id: str | None
    adapter_version: str | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class ReadableResourceRecord:
    id: str
    library_id: str
    book_id: str
    source_node_id: str
    adapter_id: str
    adapter_version: str
    media_kind: str
    format: str
    enablement_state: ResourceEnablementState
    import_state: ResourceImportState
    published_run_id: str | None
    active_import_run_id: str | None


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


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class UnitOfWorkPort(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class LibraryConfigPort(Protocol):
    def get_library(self, library_id: str) -> LibrarySourceTreeConfig: ...

    def source_node_count(self, library_id: str) -> int: ...

    def update_organization_mode(
        self,
        library_id: str,
        mode: TargetLibraryOrganizationMode,
    ) -> None: ...

    def update_root_path(self, library_id: str, root_path: Path) -> None: ...

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool: ...


class SourceTreeFilesystemPort(Protocol):
    def resolve_under_root(self, root: Path, relative_path: str) -> Path: ...

    def iter_directory_entries(
        self,
        absolute_directory: Path,
    ) -> Sequence[tuple[str, SourceNodePhysicalKind, int | None, int]]: ...

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


class SourceNodeRepositoryPort(Protocol):
    def get_by_path_key(
        self, library_id: str, path_key: str
    ) -> SourceNodeRecord | None: ...

    def get(self, source_node_id: str) -> SourceNodeRecord | None: ...

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]: ...

    def refresh_observed(
        self,
        source_node_id: str,
        entry: ObservedSourceEntry,
    ) -> SourceNodeRecord: ...

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]: ...

    def delete_subtree(self, source_node_id: str) -> None: ...

    def get_interpretation(
        self, source_node_id: str
    ) -> InterpretationRecord | None: ...

    def upsert_interpretation(
        self,
        *,
        source_node_id: str,
        result: str,
        source: str,
        adapter_id: str | None,
        adapter_version: str | None,
        reason_code: str | None,
        sample_relative_paths: str | None,
        sample_count: int | None,
        max_entries_visited: int | None,
        max_depth: int | None,
        time_budget_ms: int | None,
        termination_reason: str | None,
        recognized_at: datetime | None,
    ) -> None: ...


class BookResourceRepositoryPort(Protocol):
    def ensure_book(
        self,
        *,
        library_id: str,
        source_node_id: str,
        title: str,
    ) -> str: ...

    def get_book_id_for_source_node(self, source_node_id: str) -> str | None: ...

    def get_resource_by_source_node(
        self, source_node_id: str
    ) -> ReadableResourceRecord | None: ...

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None: ...

    def create_pending_resource(
        self,
        *,
        library_id: str,
        book_id: str,
        source_node_id: str,
        adapter: ResourceAdapterSpec,
        active_import_run_id: str,
    ) -> ReadableResourceRecord: ...

    def cas_set_active_import_run(
        self,
        resource_id: str,
        *,
        expected_active_run_id: str | None,
        new_active_run_id: str | None,
    ) -> bool: ...

    def set_enablement(
        self,
        resource_id: str,
        state: ResourceEnablementState,
    ) -> None: ...

    def publish_resource(
        self,
        *,
        resource_id: str,
        published_run_id: str,
        adapter: ResourceAdapterSpec,
        title: str,
    ) -> None: ...

    def mark_resource_failed(self, resource_id: str) -> None: ...

    def clear_active_import_run(self, resource_id: str) -> None: ...

    def upsert_asset(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        published_run_id: str,
        role: AssetRole,
        import_state: AssetImportState,
        sequence_index: int | None,
        sort_key: str | None,
        failure_reason: str | None,
    ) -> str: ...

    def count_ready_assets_for_published_run(
        self, resource_id: str, published_run_id: str
    ) -> int: ...

    def find_outermost_directory_resource(
        self,
        library_id: str,
        relative_path: str,
    ) -> ReadableResourceRecord | None: ...

    def delete_library_overlay_rows(self, library_id: str) -> None: ...

    def delete_assets_for_source_nodes(
        self, source_node_ids: Sequence[str]
    ) -> tuple[str, ...]: ...

    def reevaluate_ready_after_asset_loss(self, resource_ids: Sequence[str]) -> None: ...


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

    def cleanup_stale_assets(
        self, resource_id: str, published_run_id: str
    ) -> None: ...


class WorkQueuePort(Protocol):
    def queued_item_count(self) -> int: ...

    def enqueue_library_import_task(self, task_id: str) -> None: ...

    def enqueue_library_scan(self, library_id: str) -> None: ...

    def claim_next(
        self, worker_id: str, *, lease_seconds: int
    ) -> tuple[str, str] | None:
        """Return (work_kind, target_id) where kind is scan|import."""
        ...

    def complete(self, work_kind: str, target_id: str) -> None: ...

    def heartbeat(self, work_kind: str, target_id: str, worker_id: str) -> None: ...


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
