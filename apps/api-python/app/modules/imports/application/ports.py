"""Ports for import queue and library persistence."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from app.contracts.local_metadata import LocalMetadataSource
from app.modules.imports.application.audio_types import (
    AudioBundleStructure,
    AudioFileMetadata,
)
from app.modules.imports.application.comic_types import ComicArchiveInspection
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ConversionArtifactDTO,
    ConversionProgressTaskDTO,
    DirectorySiblingSnapshotDTO,
    ImportOptions,
    ImportPreferencesDTO,
    ImportResult,
    ImportRuntimeConfig,
    ImportSystemEvent,
    ImportTaskDTO,
    SidecarMetadataDTO,
)
from app.modules.imports.application.pdf_types import (
    PdfCoverPublication,
    PdfInspection,
)
from app.modules.imports.application.query_ports import (
    ImportLibraryQueries,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata

__all__ = ["ImportLibraryQueries"]


class ImportUnitOfWork(Protocol):
    """Transaction boundary used by recoverable import checkpoints."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def release(self) -> None:
        """Commit and release the checked-out connection before external I/O."""
        ...


class ImportMetadataObserver(Protocol):
    """Schedules side effects for the final metadata snapshot of an import."""

    def schedule(self, result: ImportResult) -> None: ...


class TextConversionProgressStore(Protocol):
    """Short-transaction checkpoints used by transaction-free file conversion."""

    def ensure_task(
        self,
        import_task_id: str,
        *,
        task_id: str,
        source_path: Path,
        source_format: str,
        converter: str,
        source_key: str,
        options_json: str,
        now: int,
    ) -> ConversionProgressTaskDTO: ...

    def update_stage(
        self,
        import_task_id: str,
        conversion_task_id: str,
        *,
        status: str,
        progress: int,
        message: str,
        conversion_values: Mapping[str, object] | None,
        now: int,
    ) -> None: ...

    def record_failure(
        self,
        import_task_id: str,
        conversion_task_id: str,
        *,
        retryable: bool,
        error_code: str,
        summary: str,
        now: int,
    ) -> None: ...


class ImportTaskStore(Protocol):
    """Persistence for import-task queue state transitions."""

    def recover_stale(self, *, now: int, message: str) -> int: ...

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: int,
    ) -> ImportTaskDTO | None: ...

    def fail_claimed(
        self,
        task: ImportTaskDTO,
        *,
        error_code: str,
        error_summary: str,
        message: str,
        retryable: bool,
        now: int,
    ) -> bool: ...

    def stage_failure_event(
        self,
        task: ImportTaskDTO,
        *,
        error_summary: str,
        now: int,
    ) -> None: ...

    def library_exists(self, library_id: str) -> bool: ...

    def mark_download_completed(
        self,
        *,
        source_path: str,
        book_id: str,
        updated_at: int,
    ) -> None: ...


class LibraryImportStore(Protocol):
    """Named library/import writes used by media import commands.

    Replaces transitional model-CRUD helpers. Each method is bound to one
    aggregate write; callers pass explicit column maps (``dict[str, object]``),
    never ``dict[str, Any]`` dump helpers.
    """

    def update_import_task(
        self, task_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def apply_import_completion(
        self,
        *,
        task_updates: tuple[tuple[str, Mapping[str, object]], ...],
        volume_updates: tuple[tuple[str, Mapping[str, object]], ...],
    ) -> None: ...

    def insert_import_asset(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_import_asset(
        self, asset_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]: ...

    def update_library_work(
        self, work_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_library_file(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_library_file(
        self, file_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def get_library_file(self, file_id: str) -> dict[str, object] | None: ...

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_library_reading_unit(
        self, unit_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None: ...

    def delete_library_reading_unit(self, unit_id: str) -> None: ...

    def insert_library_metadata(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_library_reading_progress(
        self,
        progress_id: str,
        *,
        columns: dict[str, object],
    ) -> None: ...

class ImportPipeline(Protocol):
    """Media import orchestrator used after a task is claimed."""

    def import_managed_book(
        self,
        settings: ImportRuntimeConfig,
        options: ImportOptions,
    ) -> ImportResult: ...

    def complete_import(self) -> None: ...


class ImportOrchestrationServices(Protocol):
    def load_preferences(self) -> ImportPreferencesDTO: ...

    def load_local_metadata_priority(self) -> tuple[LocalMetadataSource, ...]: ...

    def convert_text(
        self, import_task_id: str, source_path: Path
    ) -> ConversionArtifactDTO: ...

    def bind_conversion_result(
        self, idempotency_key: str, derived_volume_id: str
    ) -> None: ...

    def recognize_identity(
        self, path: Path, original_name: str | None
    ) -> BookIdentityDTO: ...

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO: ...

    def parse_filename_identity(self, filename: str) -> BookIdentityDTO: ...

    def monitor_root_path(self, library_id: str | None) -> Path | None: ...

    def list_sibling_files(self, path: Path) -> DirectorySiblingSnapshotDTO: ...

    def read_sidecar_metadata(
        self, path: Path, *, directory_fallback: bool
    ) -> SidecarMetadataDTO | None: ...

    def sync_work_facets(self, work_id: str) -> None: ...

    def stage_system_event(self, event: ImportSystemEvent) -> None: ...

    def ensure_default_cover(self) -> str: ...

    def cover_status(self, value: object) -> str: ...

    def is_default_cover_path(self, value: object) -> bool: ...

    def inspect_comic_archive(
        self, path: Path, original_name: str | None
    ) -> ComicArchiveInspection: ...

    def publish_comic_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
        entry_name: str,
    ) -> str: ...

    def publish_sidecar_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
    ) -> str: ...

    def inspect_audio_bundle(self, path: Path) -> AudioBundleStructure | None: ...

    def parse_audio_metadata(self, path: Path) -> AudioFileMetadata: ...

    def publish_audio_cover(
        self,
        storage_root: Path,
        work_id: str,
        version_id: str,
        metadata_items: tuple[AudioFileMetadata, ...],
        *,
        bundle_root: Path | None = None,
    ) -> str | None: ...

    def inspect_reflowable_book(
        self, path: Path, source_format: str
    ) -> ReflowableBookMetadata: ...

    def publish_reflowable_cover(
        self,
        storage_root: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
        metadata: ReflowableBookMetadata,
    ) -> str | None: ...

    def inspect_pdf(self, path: Path, original_name: str | None) -> PdfInspection: ...

    def publish_pdf_cover(
        self,
        storage_root: Path,
        source_path: Path,
        work_id: str,
        version_id: str,
        volume_id: str,
    ) -> PdfCoverPublication: ...


class ImportSourceProbe(Protocol):
    def exists(self, path: Path) -> bool: ...
