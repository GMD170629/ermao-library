"""Application ports for the ADR 0018 single-consumer ContinueImport pipeline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.modules.imports.application.audio_types import AudioFileMetadata
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
)
from app.modules.imports.domain.directory_probe import (
    DirectoryProbeDecision,
)
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterSpec,
    source_format_for_filename,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy, ScanScope
from app.modules.library.public import (
    AdapterIdentity,
    AssetRole,
    BookResourceRepositoryPort,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    ResourceNavigationUnitInput,
    SourceNodePhysicalKind,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.metadata.public import ResolvedLocalMetadata

__all__ = [
    "WORKER_INTERRUPTED",
    "AdapterIdentity",
    "AssetTechnicalMetadata",
    "AudioMetadataInspectorPort",
    "BookImportTaskQueuePort",
    "BookImportTaskRecord",
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
    "MissingEntryPolicy",
    "ObservedSourceEntry",
    "ParsedAssetPayload",
    "PipelineLogPort",
    "PreparedLocalCover",
    "ReadableResourceRecord",
    "RegularFileObservation",
    "ResourceAdapterExecutorPort",
    "ResourceAdapterSpec",
    "ResourceNavigationUnitInput",
    "SidecarWritebackPort",
    "SourceNodeDeletionPort",
    "SourceNodeRecord",
    "SourceNodeRepositoryPort",
    "SourceTreeFilesystemPort",
    "UnitOfWorkPort",
    "UnreadableDirectoryEntry",
    "adapter_identity",
]

ImportTaskKind = Literal[
    "SCAN_LIBRARY",
    "CONTINUE_SOURCE",
    "IMPORT_ASSET",
    "IMPORT_RESOURCE",
    "IDENTIFY_BOOK",
    "IMPORT_BOOK",
]
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
    missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE
    scan_scopes: tuple[ScanScope, ...] | None = None


@dataclass(frozen=True, slots=True)
class BookImportTaskRecord:
    id: str
    book_id: str
    library_id: str
    source_node_id: str
    state: ImportTaskState
    phase: str
    request_version: int
    execution_version: int | None
    work: BookWorkState
    resource_cursor: str | None
    error_summary: str | None
    directory_resource_id: str | None = None
    directory_member_cursor: str | None = None
    directory_cover_cursor: str | None = None


class BookImportTaskQueuePort(Protocol):
    def refresh_scan_gate_page(self) -> int: ...

    def request_book_work(
        self, *, book_id: str, work: BookWork, requested_at: datetime
    ) -> BookImportTaskRecord: ...

    def claim_next_book(self, *, started_at: datetime) -> BookImportTaskRecord | None: ...

    def claim_book_task(
        self, task_id: str, *, started_at: datetime
    ) -> BookImportTaskRecord | None: ...

    def get_book_task(self, task_id: str) -> BookImportTaskRecord | None: ...

    def book_identification_complete(self, book_id: str) -> bool: ...

    def book_run_is_current(
        self,
        task_id: str,
        *,
        execution_version: int,
        require_latest_request: bool = False,
    ) -> bool: ...

    def advance_book_resource_cursor(
        self, task_id: str, *, execution_version: int, resource_id: str
    ) -> bool: ...

    def advance_directory_member_cursor(
        self, task_id: str, *, execution_version: int,
        resource_id: str, member_id: str,
    ) -> bool: ...

    def advance_directory_cover_cursor(
        self, task_id: str, *, execution_version: int,
        resource_id: str, asset_id: str,
    ) -> bool: ...

    def advance_book_phase(
        self, task_id: str, *, execution_version: int, phase: str
    ) -> bool: ...

    def finish_book_run(
        self, task_id: str, *, execution_version: int, finished_at: datetime
    ) -> BookImportTaskRecord | None: ...

    def fail_book_run(
        self,
        task_id: str,
        *,
        execution_version: int,
        error_summary: str,
        failed_at: datetime,
        partial_failure: bool = False,
    ) -> BookImportTaskRecord | None: ...

    def continue_book_task(
        self, task_id: str, *, continued_at: datetime, force: bool = False
    ) -> tuple[BookImportTaskRecord, bool] | None: ...


@dataclass(frozen=True, slots=True)
class AssetTechnicalMetadata:
    codec: str | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    disc_number: int | None = None
    track_number: int | None = None
    page_count: int | None = None


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


@dataclass(frozen=True, slots=True)
class UnreadableDirectoryEntry:
    """A visible directory entry whose type or stat facts could not be read."""

    name: str
    error: OSError | None = field(default=None, compare=False)


@dataclass(frozen=True, slots=True)
class RegularFileObservation:
    observed_size_bytes: int
    observed_mtime_ns: int


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class UnitOfWorkPort(Protocol):
    def release_before_io(self) -> None: ...

    def transaction(
        self, *, before_rollback: Callable[[Exception], None] | None = None,
    ) -> AbstractContextManager[None]: ...

    def rollback(self) -> None: ...

    def recover_after_failure(self) -> None: ...


class SourceTreeFilesystemPort(Protocol):
    def metadata_input_observations(
        self, source: Path, *, directory: bool
    ) -> tuple[tuple[str, int | None, int | None], ...]: ...

    def resolve_under_root(self, root: Path, relative_path: str) -> Path: ...

    def iter_directory_entries(
        self,
        absolute_directory: Path,
    ) -> Iterator[DirectoryEntry | UnreadableDirectoryEntry]: ...

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
        observations: tuple[DirectoryEntry, ...] | None = None,
        listings: dict[str, tuple[DirectoryEntry, ...]] | None = None,
    ) -> DirectoryProbeDecision: ...

    def path_is_readable_directory(self, path: Path) -> bool: ...

    def observe_readable_file(self, path: Path) -> RegularFileObservation | None: ...


class SourceNodeDeletionPort(Protocol):
    def delete_source_node(self, source_node_id: str) -> None: ...


class LibraryImportTaskQueuePort(Protocol):
    def request_library_scan(
        self,
        library_id: str,
        *,
        missing_entry_policy: MissingEntryPolicy,
        scan_scopes: tuple[ScanScope, ...] | None = None,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        """Return the one queued scan, creating it when absent."""

    def request_source_scan(
        self,
        *,
        library_id: str,
        source_node_id: str,
        missing_entry_policy: MissingEntryPolicy,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        """Return one active source scan, preserving stronger queued intent."""

    def request_import_resource(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        changed: bool = False,
        force: bool = False,
    ) -> LibraryImportTaskRecord | None:
        """Coalesce resource work; changes during execution survive completion."""

    def next_queued(self, *, started_at: datetime | None = None) -> LibraryImportTaskRecord | None: ...

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

    def has_incomplete_ranges(self, library_id: str) -> bool:
        """Whether this library still has durable incomplete scan ranges."""

    def apply_scan_round(
        self,
        task_id: str | None,
        library_id: str,
        *,
        resolved: tuple[ScanScope, ...],
        incomplete: tuple[ScanScope, ...],
    ) -> None:
        """Replace visited ranges with this round's remaining incomplete ranges.

        ``resolved`` removes old gaps this round actually enumerated;
        ``incomplete`` adds the exact failed and unvisited ranges. Both happen
        in one transaction so an incomplete input is never momentarily released.
        """


class ResourceAdapterExecutorPort(Protocol):
    def reset_inspection_cache(self) -> None:
        """Start a new scan round; implementations without caches do nothing."""

    def inspect_resource_metadata(
        self,
        *,
        resource_absolute_path: Path,
        adapter: ResourceAdapterSpec,
        local_metadata_priority: tuple[LocalMetadataSource, ...],
    ) -> ResolvedLocalMetadata | None:
        """Read directory-owned metadata outside file extraction and transactions."""

    def parse_file(
        self,
        *,
        absolute_path: Path,
        resource_absolute_path: Path | None = None,
        adapter: ResourceAdapterSpec,
        role: AssetRole,
        local_metadata_priority: tuple[LocalMetadataSource, ...],
    ) -> FileParseResult: ...


class AudioMetadataInspectorPort(Protocol):
    def inspect(self, path: Path) -> AudioFileMetadata: ...


class LocalMetadataPriorityPort(Protocol):
    def load(self) -> tuple[LocalMetadataSource, ...]: ...


class LocalCoverPublicationPort(Protocol):
    def exists(self, stored_path: str) -> bool: ...

    def retain_audio_candidate(self, *, resource_id: str, content: bytes) -> str: ...

    def read_candidate(self, stored_path: str) -> bytes | None: ...

    def matches(self, stored_path: str | None, content: bytes) -> bool: ...

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
        error: BaseException | None = None,
        step: str | None = None,
        source_node_id: str | None = None,
    ) -> None: ...


class SidecarWritebackPort(Protocol):
    def schedule_after_commit(self, resource_id: str) -> None: ...
