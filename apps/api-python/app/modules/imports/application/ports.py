"""Ports for import queue and library persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.modules.imports.application.audio_types import (
    AudioBundleStructure,
    AudioFileMetadata,
)
from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ConversionArtifactDTO,
    ImportOptions,
    ImportPreferencesDTO,
    ImportResult,
    ImportRuntimeConfig,
    ImportSystemEvent,
    ImportTaskDTO,
    StageImportCommand,
)
from app.modules.imports.application.query_ports import (
    ImportLibraryQueries as ImportLibraryQueries,
)
from app.modules.imports.application.reflowable_types import ReflowableBookMetadata


class ImportUnitOfWork(Protocol):
    """Transaction boundary used by recoverable import checkpoints."""

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class ImportTaskStore(Protocol):
    """Persistence for import-task queue state transitions."""

    def stage(self, command: StageImportCommand) -> tuple[ImportTaskDTO, bool]: ...

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

    def monitor_folder_exists(self, monitor_folder_id: str) -> bool: ...

    def link_work_to_monitor_shelf(
        self,
        monitor_folder_id: str | None,
        work_id: str,
        *,
        created_at: int,
    ) -> None: ...

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

    def insert_import_task(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_import_task(
        self, task_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_import_asset(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_import_asset(
        self, asset_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]: ...

    def insert_library_work(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_library_work(
        self, work_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_library_edition(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_library_edition(
        self, edition_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_library_volume(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

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

    def update_library_consumption_state(
        self,
        state_id: str,
        *,
        columns: dict[str, object],
    ) -> None: ...

    def insert_organize_job(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_organize_job(
        self, job_id: str, *, columns: dict[str, object]
    ) -> None: ...

    def insert_metadata_lookup_task(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]: ...

    def update_metadata_lookup_task(
        self, task_id: str, *, columns: dict[str, object]
    ) -> None: ...


class ImportPipeline(Protocol):
    """Media import orchestrator used after a task is claimed."""

    def import_managed_book(
        self,
        settings: ImportRuntimeConfig,
        options: ImportOptions,
    ) -> ImportResult: ...

    def finalize_publications(self) -> None: ...

    def rollback_publications(self) -> None: ...


class ImportOrchestrationServices(Protocol):
    def load_preferences(self) -> ImportPreferencesDTO: ...

    def convert_text(
        self, import_task_id: str, source_path: Path
    ) -> ConversionArtifactDTO: ...

    def recognize_identity(
        self, path: Path, original_name: str | None
    ) -> BookIdentityDTO: ...

    def logical_import_path(self, path: Path, original_name: str | None) -> str: ...

    def sync_work_facets(self, work_id: str) -> None: ...

    def stage_system_event(self, event: ImportSystemEvent) -> None: ...

    def ensure_default_cover(self) -> str: ...

    def cover_status(self, value: object) -> str: ...

    def is_default_cover_path(self, value: object) -> bool: ...

    def inspect_audio_bundle(self, path: Path) -> AudioBundleStructure | None: ...

    def parse_audio_metadata(self, path: Path) -> AudioFileMetadata: ...

    def publish_audio_cover(
        self,
        storage_root: Path,
        work_id: str,
        edition_id: str,
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
        edition_id: str,
        metadata: ReflowableBookMetadata,
    ) -> str | None: ...


class ImportSourceProbe(Protocol):
    def exists(self, path: Path) -> bool: ...
