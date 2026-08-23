"""Application ports for the ADR 0018 single-consumer ContinueImport pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.modules.imports.application.local_metadata import ResolvedLocalMetadata
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
    ProbeTerminationReason,
)
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterSpec,
    source_format_for_filename,
)
from app.modules.library.domain.readable_resource_states import AssetRole
from app.modules.library.domain.source_nodes import SourceNodePhysicalKind
from app.modules.library.public import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    ResourceNavigationUnitInput,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)

__all__ = [
    "WORKER_INTERRUPTED",
    "AdapterIdentity",
    "AssetTechnicalMetadata",
    "BookResourceRepositoryPort",
    "ClockPort",
    "DirectoryEntry",
    "FileParseResult",
    "ImportTaskKind",
    "ImportTaskState",
    "InterpretationRecord",
    "LibraryConfigPort",
    "LibraryImportTaskQueuePort",
    "LibraryImportTaskRecord",
    "LibrarySourceTreeConfig",
    "LocalCoverPublicationPort",
    "LocalMetadataPriorityPort",
    "ObservedSourceEntry",
    "ParsedAssetPayload",
    "PipelineLogPort",
    "PreparedLocalCover",
    "ReadableResourceRecord",
    "ResourceAdapterExecutorPort",
    "ResourceAdapterSpec",
    "ResourceNavigationUnitInput",
    "SidecarWritebackPort",
    "SourceNodeRecord",
    "SourceNodeRepositoryPort",
    "SourceTreeFilesystemPort",
    "UnitOfWorkPort",
    "adapter_identity",
]

ImportTaskKind = Literal["SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_ASSET"]
ImportTaskState = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED"]

WORKER_INTERRUPTED = "WORKER_INTERRUPTED"


def adapter_identity(
    spec: ResourceAdapterSpec, *, source_name: str | None = None
) -> AdapterIdentity:
    source_format = (
        source_format_for_filename(spec, source_name)
        if source_name is not None
        else spec.format_label
    )
    return AdapterIdentity(
        adapter_id=spec.adapter_id.value,
        adapter_version=spec.adapter_version,
        media_kind=spec.media_kind,
        format_label=source_format,
    )


@dataclass(frozen=True, slots=True)
class LibraryImportTaskRecord:
    id: str
    kind: ImportTaskKind
    library_id: str
    state: ImportTaskState
    resource_id: str | None
    source_node_id: str | None
    role: AssetRole | None
    error_summary: str | None


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
    navigation_units: tuple[ResourceNavigationUnitInput, ...] = ()


@dataclass(frozen=True, slots=True)
class FileParseResult:
    ok: bool
    adapter: ResourceAdapterSpec
    resource_title: str | None
    asset: ParsedAssetPayload | None
    error_code: str | None
    error_summary: str | None
    local_metadata: ResolvedLocalMetadata | None = None


@dataclass(frozen=True, slots=True)
class PreparedLocalCover:
    temporary_path: Path
    final_path: Path
    stored_path: str


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


class LibraryImportTaskQueuePort(Protocol):
    def enqueue(
        self,
        *,
        kind: ImportTaskKind,
        library_id: str,
        resource_id: str | None = None,
        source_node_id: str | None = None,
        role: AssetRole | None = None,
    ) -> LibraryImportTaskRecord: ...

    def ensure_import_asset_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
    ) -> LibraryImportTaskRecord | None:
        """Create or requeue FAILED task; return None when already SUCCEEDED."""

    def next_queued(self) -> LibraryImportTaskRecord | None: ...

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None: ...

    def mark_running(self, task_id: str, *, started_at: datetime) -> None: ...

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None: ...

    def mark_failed(
        self,
        task_id: str,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None: ...

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int: ...

    def requeue_failed_for_library(self, library_id: str) -> int: ...

    def requeue_failed_for_source(self, source_node_id: str) -> int: ...

    def has_active_kind(
        self,
        *,
        kind: ImportTaskKind,
        library_id: str,
        source_node_id: str | None = None,
    ) -> bool: ...


class ResourceAdapterExecutorPort(Protocol):
    def parse_file(
        self,
        *,
        absolute_path: Path,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        local_metadata_priority: tuple[LocalMetadataSource, ...],
    ) -> FileParseResult: ...


class LocalMetadataPriorityPort(Protocol):
    def load(self) -> tuple[LocalMetadataSource, ...]: ...


class LocalCoverPublicationPort(Protocol):
    def prepare(self, *, resource_id: str, content: bytes) -> PreparedLocalCover: ...

    def publish(self, prepared: PreparedLocalCover) -> None: ...

    def discard(self, prepared: PreparedLocalCover) -> None: ...


class PipelineLogPort(Protocol):
    def emit(
        self,
        event: str,
        *,
        library_id: str | None = None,
        resource_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        outcome: str | None = None,
    ) -> None: ...


class SidecarWritebackPort(Protocol):
    def schedule_after_commit(self, resource_id: str) -> None: ...
