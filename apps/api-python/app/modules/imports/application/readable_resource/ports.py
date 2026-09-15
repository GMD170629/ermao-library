"""Application ports for the ADR 0018 single-consumer ContinueImport pipeline."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.modules.imports.application.audio_types import AudioFileMetadata
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
    "PreparedBookIdentification",
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
class PreparedBookIdentification:
    task_id: str
    book_id: str
    library_id: str
    source_node_id: str
    import_revision: int


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


@dataclass(frozen=True, slots=True)
class RegularFileObservation:
    observed_size_bytes: int
    observed_mtime_ns: int


class ClockPort(Protocol):
    def now(self) -> datetime: ...


class UnitOfWorkPort(Protocol):
    def release_before_io(self) -> None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

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

    def next_queued(self) -> LibraryImportTaskRecord | None: ...

    def prepare_book_identifications(self) -> tuple[PreparedBookIdentification, ...]:
        """Read a bounded batch and prepare identification intent before writes."""

    def enqueue_book_identifications(
        self, prepared: tuple[PreparedBookIdentification, ...]
    ) -> int:
        """Persist prepared intent conditionally; the caller owns the transaction."""

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

    def requeue_failed_task(
        self, task_id: str
    ) -> tuple[LibraryImportTaskRecord, bool]: ...


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
    ) -> None: ...


class SidecarWritebackPort(Protocol):
    def schedule_after_commit(self, resource_id: str) -> None: ...
