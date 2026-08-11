"""Import capability composition root."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from app.contracts.import_deletion import (
    LibraryVolumeDeletionResult,
    PreparedLibraryVolumeDeletion,
)
from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportScanJob
from app.models.settings import MonitorFolder, QueueControlOperation, SystemSetting
from app.modules.imports.application.claim import (
    claim_next_import_task as claim_next_import_task_command,
)
from app.modules.imports.application.clear_queue import (
    clear_import_queue as clear_import_queue_command,
)
from app.modules.imports.application.commands import (
    commit_import_checkpoint,
    reset_failed_import_checkpoint,
)
from app.modules.imports.application.deletion import (
    FileCleanupResult,
    ImportDeletionDatabaseResult,
    PreparedImportDeletion,
    execute_import_deletion,
)
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
    StageImportCommand,
)
from app.modules.imports.application.enqueue import (
    ImportEnqueueProjection,
    PreparedImportEnqueue,
    persist_prepared_import_enqueue,
)
from app.modules.imports.application.events import persist_prepared_import_events
from app.modules.imports.application.fail import (
    fail_claimed_import_task as fail_claimed_import_task_command,
)
from app.modules.imports.application.maintenance_commands import (
    PreparedImportRetry,
    PreparedTerminalImportClear,
    persist_import_retry,
    persist_terminal_import_clear,
)
from app.modules.imports.application.monitor_folder_commands import (
    PreparedMonitorFolderCreate,
    PreparedMonitorFolderDelete,
    PreparedMonitorFolderUpdate,
    persist_monitor_folder_create,
    persist_monitor_folder_delete,
    persist_monitor_folder_update,
)
from app.modules.imports.application.ports import ImportMetadataObserver
from app.modules.imports.application.process import (
    process_import_task as process_import_task_command,
)
from app.modules.imports.application.queue_control import (
    PreparedImportQueueOperationCheckpoint,
)
from app.modules.imports.application.queue_control import (
    persist_import_queue_operation_checkpoint as persist_queue_operation_checkpoint,
)
from app.modules.imports.application.recover import (
    recover_stale_import_tasks as recover_stale_import_tasks_command,
)
from app.modules.imports.application.rescan import persist_rescan_completion
from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
)
from app.modules.imports.application.scan_checkpoint import (
    PreparedScanCheckpoint,
    persist_scan_checkpoint,
)
from app.modules.imports.application.scan_jobs import PreparedImportScanJob
from app.modules.imports.application.scan_requests import persist_scan_requests
from app.modules.imports.application.shelf_link import (
    PreparedImportShelfLink,
    persist_import_shelf_link,
)
from app.modules.imports.application.work_queue_dto import (
    ImportScanJobDTO,
    ImportWorkItemDTO,
)
from app.modules.imports.infrastructure import import_http as import_http_store
from app.modules.imports.infrastructure import library_queries as library_repository
from app.modules.imports.infrastructure import monitor as monitor_repository
from app.modules.imports.infrastructure import tasks as task_repository
from app.modules.imports.infrastructure import work_queue as persistent_work_queue
from app.modules.imports.infrastructure.deletion_files import LocalImportDeletionFiles
from app.modules.imports.infrastructure.deletion_write import (
    SqlAlchemyImportTaskDeletionStore,
)
from app.modules.imports.infrastructure.directory_scan import (
    IgnoredImportSource,
    ImportIgnoreReason,
    MonitorFolderConfig,
    ScanSummary,
    import_file_ignore_reason,
    import_source_meets_minimum_size,
    is_proven_audio_bundle_directory,
    monitor_folder_config,
    scan_directory_for_imports,
    should_ignore_file,
    should_ignore_path,
)
from app.modules.imports.infrastructure.enqueue_write import (
    SqlAlchemyPreparedImportEnqueueStore,
    execute_prepared_import_enqueue,
    load_import_enqueue_projection,
    prepare_import_enqueue,
)
from app.modules.imports.infrastructure.maintenance_write import (
    SqlAlchemyImportMaintenanceWriteStore,
)
from app.modules.imports.infrastructure.managed_pipeline import SessionImportPipeline
from app.modules.imports.infrastructure.monitor_folder_write import (
    SqlAlchemyMonitorFolderWriteStore,
)
from app.modules.imports.infrastructure.queue_maintenance import (
    SqlAlchemyImportQueueMaintenanceStore,
)
from app.modules.imports.infrastructure.rescan import SqlAlchemyRescanCompletionStore
from app.modules.imports.infrastructure.scan_batch_store import (
    load_scan_candidate_projection,
    prepare_scan_candidate_batch,
    prepare_scan_sources,
)
from app.modules.imports.infrastructure.scan_checkpoint import (
    SqlAlchemyScanCheckpointStore,
)
from app.modules.imports.infrastructure.scan_requests import SqlAlchemyScanRequestStore
from app.modules.imports.infrastructure.shelf_link import SqlAlchemyImportShelfLinkStore
from app.modules.imports.infrastructure.source_probe import LocalImportSourceProbe
from app.modules.imports.infrastructure.streaming_scan import StreamingDirectoryScanner
from app.modules.imports.infrastructure.system_events import (
    SqlAlchemyPreparedImportEventStore,
)
from app.modules.imports.infrastructure.task_store import SqlAlchemyImportTaskStore
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.modules.library.infrastructure.deletion import (
    execute_prepared_import_volume_deletion,
    load_prepared_import_volume_deletion,
)
from app.modules.system.domain.queue import TERMINAL_OPERATION_STATUSES
from app.modules.system.public import PreparedSystemEvent
from app.services.import_preferences import (
    DEFAULT_STABILITY_CHECK_ENABLED,
    IMPORT_ALLOWED_EXTENSIONS_KEY,
    IMPORT_AUTO_CONVERT_KEY,
    IMPORT_IGNORE_PATTERNS_KEY,
    IMPORT_PREFERENCE_KEYS,
    IMPORT_STABILITY_ENABLED_KEY,
    IMPORT_STABILITY_SECONDS_KEY,
    ImportPreferences,
    default_stability_seconds,
    normalize_allowed_extensions,
    normalize_ignore_patterns,
    normalize_import_setting_value,
    normalize_stability_seconds,
)
from app.services.metadata_file_writeback import schedule_work_metadata_writebacks
from app.services.system_events import (
    prepare_system_event,
    write_prepared_system_events,
)


@dataclass(frozen=True, slots=True)
class _ScanWorkProjection:
    job: Mapping[str, object] | None
    folder: Mapping[str, object] | None
    active_imports: int
    preference_values: tuple[tuple[str, str], ...]


def _preferences_from_raw_values(
    raw_values: tuple[tuple[str, str], ...],
) -> ImportPreferences:
    values = dict(raw_values)
    stability_enabled = normalize_import_setting_value(
        IMPORT_STABILITY_ENABLED_KEY,
        values.get(IMPORT_STABILITY_ENABLED_KEY),
    )
    auto_convert = normalize_import_setting_value(
        IMPORT_AUTO_CONVERT_KEY,
        values.get(IMPORT_AUTO_CONVERT_KEY),
    )
    return ImportPreferences(
        stability_check_enabled=(
            stability_enabled
            if isinstance(stability_enabled, bool)
            else DEFAULT_STABILITY_CHECK_ENABLED
        ),
        stability_check_seconds=(
            normalize_stability_seconds(values[IMPORT_STABILITY_SECONDS_KEY])
            if IMPORT_STABILITY_SECONDS_KEY in values
            else default_stability_seconds()
        ),
        auto_convert_to_epub=(auto_convert if isinstance(auto_convert, bool) else True),
        allowed_extensions=normalize_allowed_extensions(
            values.get(IMPORT_ALLOWED_EXTENSIONS_KEY)
        ),
        ignore_patterns=normalize_ignore_patterns(
            values.get(IMPORT_IGNORE_PATTERNS_KEY)
        ),
    )


def _stage_import_event(
    db: Session,
    *,
    source: str,
    action: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    prepared_event = prepare_system_event(
        source=source,
        action=action,
        message=message,
        level=level,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
    write_prepared_system_events(db, [prepared_event])


def persist_import_events(
    db: Session,
    events: tuple[PreparedSystemEvent, ...],
) -> None:
    persist_prepared_import_events(
        SqlAlchemyPreparedImportEventStore(db),
        SqlAlchemyImportUnitOfWork(db),
        events,
    )


def stage_import_events(
    db: Session,
    events: tuple[PreparedSystemEvent, ...],
) -> None:
    """Write already prepared events in the caller-owned state transaction."""

    SqlAlchemyPreparedImportEventStore(db).write(events)


def persist_import_rescan_completion(
    db: Session,
    *,
    setting_key: str,
    setting_value: str,
    checkpoint_at: datetime,
    scan_jobs: tuple[PreparedImportScanJob, ...],
    events: tuple[PreparedSystemEvent, ...],
) -> int:
    return persist_rescan_completion(
        SqlAlchemyRescanCompletionStore(db),
        SqlAlchemyImportUnitOfWork(db),
        setting_key=setting_key,
        setting_value=setting_value,
        checkpoint_at=checkpoint_at,
        scan_jobs=scan_jobs,
        events=events,
    )


def persist_import_scan_requests(
    db: Session,
    scan_jobs: tuple[PreparedImportScanJob, ...],
    events: tuple[PreparedSystemEvent, ...],
) -> int:
    """Persist prepared scan jobs and their events in one named transaction."""

    return persist_scan_requests(
        SqlAlchemyScanRequestStore(db),
        SqlAlchemyImportUnitOfWork(db),
        scan_jobs,
        events,
    )


def persist_terminal_import_tasks_clear(
    db: Session,
    prepared: PreparedTerminalImportClear,
) -> int:
    return persist_terminal_import_clear(
        SqlAlchemyImportMaintenanceWriteStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def persist_import_task_retry(
    db: Session,
    prepared: PreparedImportRetry,
) -> None:
    persist_import_retry(
        SqlAlchemyImportMaintenanceWriteStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def persist_watched_import_shelf_link(
    db: Session,
    prepared: PreparedImportShelfLink,
) -> None:
    persist_import_shelf_link(
        SqlAlchemyImportShelfLinkStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def persist_import_monitor_folder_create(
    db: Session,
    prepared: PreparedMonitorFolderCreate,
) -> None:
    persist_monitor_folder_create(
        SqlAlchemyMonitorFolderWriteStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def persist_import_monitor_folder_update(
    db: Session,
    prepared: PreparedMonitorFolderUpdate,
) -> None:
    persist_monitor_folder_update(
        SqlAlchemyMonitorFolderWriteStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def persist_import_monitor_folder_delete(
    db: Session,
    prepared: PreparedMonitorFolderDelete,
) -> bool:
    return persist_monitor_folder_delete(
        SqlAlchemyMonitorFolderWriteStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def load_persisted_scan_requests(
    db: Session,
    scan_jobs: tuple[PreparedImportScanJob, ...],
) -> list[ImportScanJobDTO]:
    return persistent_work_queue.list_scan_jobs_for_prepared_requests(db, scan_jobs)


class _SqlAlchemyImportQueueOperationCheckpointStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def persist(self, checkpoint: PreparedImportQueueOperationCheckpoint) -> None:
        status = checkpoint.status
        started_at = case(
            (
                QueueControlOperation.started_at.is_(None)
                & (status in {"waiting", "running", "completed"}),
                checkpoint.checkpoint_at,
            ),
            else_=QueueControlOperation.started_at,
        )
        finished_at = (
            checkpoint.checkpoint_at
            if status in TERMINAL_OPERATION_STATUSES
            else QueueControlOperation.finished_at
        )
        statement = (
            update(QueueControlOperation)
            .where(QueueControlOperation.id == checkpoint.operation_id)
            .values(
                status=status,
                message_code=checkpoint.message_code,
                started_at=started_at,
                finished_at=finished_at,
                updated_at=checkpoint.checkpoint_at,
            )
        )
        self._db.execute(statement)
        SqlAlchemyPreparedImportEventStore(self._db).write(checkpoint.events)


def persist_import_queue_operation_checkpoint(
    db: Session,
    checkpoint: PreparedImportQueueOperationCheckpoint,
) -> None:
    persist_queue_operation_checkpoint(
        _SqlAlchemyImportQueueOperationCheckpointStore(db),
        SqlAlchemyImportUnitOfWork(db),
        checkpoint,
    )


class _ImportMetadataOpfObserver(ImportMetadataObserver):
    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    def schedule(self, result: ImportResult) -> None:
        schedule_work_metadata_writebacks(
            self._db,
            work_id=result.work_id,
            media_version_id=result.media_version_id,
            volume_id=result.volume_id,
            source="IMPORT_METADATA",
            settings=self._settings,
        )


def import_managed_book(
    db: Session, settings: Settings, options: ImportOptions
) -> ImportResult:
    """Session-bound composition wrapper for media import."""

    unit_of_work = SqlAlchemyImportUnitOfWork(db)
    try:
        unit_of_work.release()
        pipeline = SessionImportPipeline(db, settings, unit_of_work)
        result = pipeline.import_managed_book(_runtime_config(settings), options)
        pipeline.complete_import()
        commit_import_checkpoint(unit_of_work)
        return result
    except Exception:
        reset_failed_import_checkpoint(unit_of_work)
        raise


def save_uploaded_files(
    command: SaveUploadedFilesCommand,
) -> tuple[SavedUploadFile, ...]:
    """Compose the browser-upload save use case with local atomic publication."""

    return SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(command)


def _runtime_config(settings: Settings) -> ImportRuntimeConfig:
    return ImportRuntimeConfig(
        storage_root=settings.resolved_storage_root,
        audiobook_max_file_bytes=settings.audiobook_max_file_bytes,
    )


def load_known_import_paths(db: Session) -> set[Path]:
    return monitor_repository.load_known_import_paths(db)


def prepare_import_enqueue_command(
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> StageImportCommand:
    """Resolve the source path before any enqueue projection Session is opened."""

    return StageImportCommand(
        source_path=Path(source_path).expanduser().resolve(),
        origin=origin,
        original_name=original_name,
        requested_title=requested_title,
        requested_author=requested_author,
        monitor_folder_id=monitor_folder_id,
        message=message,
        allow_terminal_requeue=allow_terminal_requeue,
    )


def load_import_enqueue_command_projection(
    db: Session,
    command: StageImportCommand,
) -> ImportEnqueueProjection:
    return load_import_enqueue_projection(
        db,
        canonical_source_path=str(command.source_path),
        monitor_folder_id=command.monitor_folder_id,
        allow_terminal_requeue=command.allow_terminal_requeue,
    )


def prepare_import_enqueue_write(
    command: StageImportCommand,
    projection: ImportEnqueueProjection,
    *,
    available_at: datetime,
) -> PreparedImportEnqueue:
    return prepare_import_enqueue(
        command,
        projection,
        available_at=available_at,
    )


def execute_import_enqueue_write(
    db: Session,
    prepared: PreparedImportEnqueue,
) -> None:
    execute_prepared_import_enqueue(db, prepared)


def persist_import_enqueue_write(
    db: Session,
    prepared: PreparedImportEnqueue,
) -> tuple[ImportTaskDTO, bool]:
    return persist_prepared_import_enqueue(
        SqlAlchemyPreparedImportEnqueueStore(db),
        SqlAlchemyImportUnitOfWork(db),
        prepared,
    )


def import_queue_at_high_watermark(db: Session) -> bool:
    return (
        persistent_work_queue.active_import_work_count(db)
        >= persistent_work_queue.IMPORT_WORK_HIGH_WATERMARK
    )


def get_import_scan_job(db: Session, job_id: str) -> ImportScanJobDTO | None:
    return persistent_work_queue.get_scan_job(db, job_id)


def list_import_scan_jobs(
    db: Session,
    *,
    monitor_folder_ids: tuple[str, ...] | None,
    status: str | None,
) -> list[ImportScanJobDTO]:
    return persistent_work_queue.list_scan_jobs(
        db, monitor_folder_ids=monitor_folder_ids, status=status
    )


def cancel_import_scan_job(db: Session, job_id: str) -> bool:
    cancelled = persistent_work_queue.cancel_scan_job(db, job_id)
    commit_import_checkpoint(db)
    return cancelled


def import_source_already_known(db: Session, path: Path) -> bool:
    return persistent_work_queue.source_already_known(db, path)


def recover_stale_import_tasks(db: Session) -> int:
    store = SqlAlchemyImportTaskStore(db)
    return recover_stale_import_tasks_command(
        store,
        SqlAlchemyImportUnitOfWork(db),
        now=now_timestamp_ms(),
    )


def recover_interrupted_import_deletions(
    db: Session,
    settings: Settings,
) -> tuple[int, int]:
    monitor_roots = [
        Path(root).expanduser()
        for root in import_http_store.list_monitor_root_paths(db)
        if root.strip()
    ]
    files = LocalImportDeletionFiles(
        settings.resolved_storage_root,
        [settings.conversion_root, *monitor_roots],
    )
    return files.recover_pending(
        database_record_exists=lambda task_id: (
            import_http_store.get_import_task(db, task_id) is not None
        )
    )


def _recover_interrupted_import_deletions_without_open_session(
    db_factory: Callable[[], Session],
    settings: Settings,
) -> tuple[int, int]:
    with db_factory() as db:
        monitor_roots = tuple(import_http_store.list_monitor_root_paths(db))
    allowed_roots = [
        Path(root).expanduser() for root in monitor_roots if root.strip()
    ]
    files = LocalImportDeletionFiles(
        settings.resolved_storage_root,
        [settings.conversion_root, *allowed_roots],
    )

    def database_record_exists(task_id: str) -> bool:
        with db_factory() as db:
            return import_http_store.get_import_task(db, task_id) is not None

    return files.recover_pending(database_record_exists=database_record_exists)


def load_import_volume_deletion(
    db: Session,
    file_paths: tuple[str, ...],
    fallback_volume_id: str | None,
) -> PreparedLibraryVolumeDeletion | None:
    return load_prepared_import_volume_deletion(
        db,
        file_paths,
        fallback_volume_id,
    )


class _SqlAlchemyPreparedImportDeletionStore:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._task_store = SqlAlchemyImportTaskDeletionStore(db)

    def write(self, prepared: PreparedImportDeletion) -> ImportDeletionDatabaseResult:
        library_result = LibraryVolumeDeletionResult(False, False, "")
        if prepared.library_deletion is not None:
            library_result = execute_prepared_import_volume_deletion(
                self._db,
                prepared.library_deletion,
            )
            if not library_result.deleted:
                raise RuntimeError("prepared library volume deletion became stale")
        deleted = self._task_store.delete_task(prepared)
        if not deleted:
            raise RuntimeError("prepared import task deletion became stale")
        return ImportDeletionDatabaseResult(
            deleted=deleted,
            deleted_library_record=library_result.deleted,
            deleted_work_record=library_result.deleted_work,
            deleted_library_database_records=int(library_result.deleted),
            library_work_id=library_result.work_id or None,
        )


def execute_recoverable_import_deletion(
    db: Session,
    settings: Settings,
    *,
    prepared: PreparedImportDeletion,
    monitor_roots: Sequence[Path],
) -> tuple[ImportDeletionDatabaseResult, FileCleanupResult]:
    files = LocalImportDeletionFiles(
        settings.resolved_storage_root,
        [settings.conversion_root, *monitor_roots],
    )
    return execute_import_deletion(
        SqlAlchemyImportUnitOfWork(db),
        files,
        _SqlAlchemyPreparedImportDeletionStore(db),
        prepared,
    )


def claim_next_import_task(
    db: Session, worker_id: str, lease_seconds: int
) -> ImportTaskDTO | None:
    store = SqlAlchemyImportTaskStore(db)
    return claim_next_import_task_command(
        store,
        SqlAlchemyImportUnitOfWork(db),
        worker_id,
        lease_seconds,
        now=now_timestamp_ms(),
    )


def process_import_task(
    db: Session, settings: Settings, task: ImportTaskDTO
) -> ImportResult:
    store = SqlAlchemyImportTaskStore(db)
    unit_of_work = SqlAlchemyImportUnitOfWork(db, close_on_release=True)
    pipeline = SessionImportPipeline(db, settings, unit_of_work)
    return process_import_task_command(
        store,
        unit_of_work,
        pipeline,
        _runtime_config(settings),
        task,
        _ImportMetadataOpfObserver(db, settings),
        now=now_timestamp_ms(),
    )


def fail_claimed_import_task(
    db: Session,
    task: ImportTaskDTO,
    error: BaseException,
) -> bool:
    store = SqlAlchemyImportTaskStore(db)
    return fail_claimed_import_task_command(
        store,
        SqlAlchemyImportUnitOfWork(db),
        task,
        error,
        now=now_timestamp_ms(),
        source_probe=LocalImportSourceProbe(),
    )


def clear_import_queue_records(db: Session) -> int:
    """Delete every persisted import task after the worker has safely stopped."""

    return clear_import_queue_command(
        SqlAlchemyImportQueueMaintenanceStore(db),
        SqlAlchemyImportUnitOfWork(db),
    )


class ImportWorkerRuntime:
    """Session-owning facade used by the thin persistent import worker loop."""

    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings
        self._scanners: dict[str, StreamingDirectoryScanner] = {}
        self._scan_progress_state: dict[str, tuple[float, int]] = {}

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with self._db_factory() as db:
            yield db

    def recover(self) -> int:
        _recover_interrupted_import_deletions_without_open_session(
            self._db_factory,
            self._settings,
        )
        with self._session() as db:
            recovered = recover_stale_import_tasks(db)
        with self._session() as db:
            projection = persistent_work_queue.load_import_queue_maintenance_projection(
                db
            )
        prepared = persistent_work_queue.prepare_import_queue_maintenance(
            projection,
            now=db_timestamp(),
        )
        with self._session() as db:
            recovered += persistent_work_queue.recover_scan_work_items(db)
            recovered += persistent_work_queue.write_prepared_import_queue_maintenance(
                db,
                prepared,
            )
            commit_import_checkpoint(db)
        return recovered

    def claim_work(
        self, worker_id: str, lease_seconds: int
    ) -> ImportWorkItemDTO | None:
        self._close_inactive_scanners()
        with self._session() as db:
            work = persistent_work_queue.claim_next_work_item(
                db,
                worker_id=worker_id,
                import_lease_seconds=lease_seconds,
            )
            commit_import_checkpoint(db)
            return work

    def claim_import(
        self,
        work_item: ImportWorkItemDTO,
        worker_id: str,
        lease_seconds: int,
    ) -> ImportTaskDTO | None:
        with self._session() as db:
            task = persistent_work_queue.claim_import_task_for_work_item(
                db,
                work_item,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
            commit_import_checkpoint(db)
            return task

    def claim(self, worker_id: str, lease_seconds: int) -> ImportTaskDTO | None:
        with self._session() as db:
            return claim_next_import_task(db, worker_id, lease_seconds)

    def process(self, task: ImportTaskDTO) -> ImportResult:
        with self._session() as db:
            return process_import_task(db, self._settings, task)

    def fail(self, task: ImportTaskDTO, error: BaseException) -> bool:
        with self._session() as db:
            return fail_claimed_import_task(db, task, error)

    def complete_work(self, work_item_id: str) -> None:
        with self._session() as db:
            persistent_work_queue.complete_work_item(db, work_item_id)
            commit_import_checkpoint(db)

    def _load_scan_work_projection(self, scan_job_id: str) -> _ScanWorkProjection:
        with self._session() as db:
            job_row = (
                db.execute(
                    select(
                        ImportScanJob.id.label("id"),
                        ImportScanJob.monitor_folder_id.label("monitorFolderId"),
                        ImportScanJob.root_path.label("rootPath"),
                        ImportScanJob.trigger.label("trigger"),
                        ImportScanJob.status.label("status"),
                        ImportScanJob.directories_scanned.label("directoriesScanned"),
                        ImportScanJob.files_scanned.label("filesScanned"),
                        ImportScanJob.candidates_found.label("candidatesFound"),
                        ImportScanJob.queued_count.label("queuedCount"),
                        ImportScanJob.skipped_count.label("skippedCount"),
                        ImportScanJob.error_count.label("errorCount"),
                        ImportScanJob.ignored_reason_counts.label(
                            "ignoredReasonCounts"
                        ),
                        ImportScanJob.error_samples.label("errorSamples"),
                        ImportScanJob.restart_count.label("restartCount"),
                        ImportScanJob.started_at.label("startedAt"),
                    ).where(ImportScanJob.id == scan_job_id)
                )
                .mappings()
                .first()
            )
            active_imports = persistent_work_queue.active_import_work_count(db)
            folder_row = None
            monitor_folder_id = (
                str(job_row["monitorFolderId"])
                if job_row is not None and job_row["monitorFolderId"]
                else None
            )
            if monitor_folder_id is not None:
                folder_row = (
                    db.execute(
                        select(
                            MonitorFolder.id.label("id"),
                            MonitorFolder.root_path.label("rootPath"),
                            MonitorFolder.shelf_id.label("shelfId"),
                            MonitorFolder.ignore_hidden.label("ignoreHidden"),
                            MonitorFolder.ignore_patterns.label("ignorePatterns"),
                            MonitorFolder.min_file_size_bytes.label(
                                "minFileSizeBytes"
                            ),
                            MonitorFolder.enabled.label("enabled"),
                        ).where(MonitorFolder.id == monitor_folder_id)
                    )
                    .mappings()
                    .first()
                )
            preference_rows = tuple(
                (str(key), str(value))
                for key, value in db.execute(
                    select(SystemSetting.key, SystemSetting.value).where(
                        SystemSetting.key.in_(tuple(IMPORT_PREFERENCE_KEYS))
                    )
                ).all()
            )
        return _ScanWorkProjection(
            job=dict(job_row) if job_row is not None else None,
            folder=dict(folder_row) if folder_row is not None else None,
            active_imports=active_imports,
            preference_values=preference_rows,
        )

    def _persist_scan_checkpoint(self, prepared: PreparedScanCheckpoint) -> None:
        with self._session() as db:
            persist_scan_checkpoint(
                SqlAlchemyScanCheckpointStore(db),
                SqlAlchemyImportUnitOfWork(db),
                prepared,
            )

    def process_scan(self, work_item: ImportWorkItemDTO) -> bool:
        try:
            return self._process_scan_once(work_item)
        except Exception:
            if work_item.scan_job_id is not None:
                self._close_scanner(work_item.scan_job_id)
                with self._session() as db:
                    persistent_work_queue.release_scan_work_item(
                        db, work_item.id, reset_attempts=False
                    )
                    commit_import_checkpoint(db)
            raise

    def _process_scan_once(self, work_item: ImportWorkItemDTO) -> bool:
        if work_item.scan_job_id is None:
            self.complete_work(work_item.id)
            return False
        projection = self._load_scan_work_projection(work_item.scan_job_id)
        job = projection.job
        if job is None or job.get("status") == "CANCELLED":
            self._persist_scan_checkpoint(
                PreparedScanCheckpoint(
                    job_id=None,
                    work_item_id=work_item.id,
                    job_values={},
                    work_disposition="complete",
                    work_available_at=None,
                    candidate_batch=None,
                    events=(),
                )
            )
            self._close_scanner(work_item.scan_job_id)
            return False

        remaining_capacity = (
            persistent_work_queue.IMPORT_WORK_HIGH_WATERMARK
            - projection.active_imports
        )
        if remaining_capacity <= 0:
            available_at = db_timestamp()
            self._persist_scan_checkpoint(
                PreparedScanCheckpoint(
                    job_id=None,
                    work_item_id=work_item.id,
                    job_values={},
                    work_disposition="release",
                    work_available_at=available_at,
                    candidate_batch=None,
                    events=(),
                )
            )
            return False

        folder = projection.folder
        job_id = str(job["id"])
        if folder is None or not bool(folder.get("enabled")):
            finished_at = db_timestamp()
            existing_samples = list(job.get("errorSamples") or [])[:99]
            failure_event = prepare_system_event(
                source="import",
                action="scan.failed",
                level="error",
                target_type="importScanJob",
                target_id=job_id,
                message="监控文件夹扫描失败",
                metadata={
                    "rootPath": str(job.get("rootPath") or ""),
                    "error": "监控文件夹已删除或停用",
                },
            )
            self._persist_scan_checkpoint(
                PreparedScanCheckpoint(
                    job_id=job_id,
                    work_item_id=work_item.id,
                    job_values={
                        "status": "FAILED",
                        "error_count": int(job.get("errorCount") or 0) + 1,
                        "error_samples": [
                            *existing_samples,
                            {
                                "path": str(job.get("rootPath") or ""),
                                "error": "监控文件夹已删除或停用",
                            },
                        ],
                        "finished_at": finished_at,
                        "updated_at": finished_at,
                    },
                    work_disposition="complete",
                    work_available_at=None,
                    candidate_batch=None,
                    events=(failure_event,),
                )
            )
            self._close_scanner(job_id)
            return False

        scanner = self._scanners.get(job_id)
        events: list[PreparedSystemEvent] = []
        restarted = scanner is None and work_item.attempts > 1
        counters = {
            "directoriesScanned": 0 if restarted else int(job.get("directoriesScanned") or 0),
            "filesScanned": 0 if restarted else int(job.get("filesScanned") or 0),
            "candidatesFound": 0 if restarted else int(job.get("candidatesFound") or 0),
            "queuedCount": 0 if restarted else int(job.get("queuedCount") or 0),
            "skippedCount": 0 if restarted else int(job.get("skippedCount") or 0),
            "errorCount": 0 if restarted else int(job.get("errorCount") or 0),
        }
        reasons = {} if restarted else dict(job.get("ignoredReasonCounts") or {})
        samples = [] if restarted else list(job.get("errorSamples") or [])
        started_at = db_timestamp() if restarted else job.get("startedAt")
        restart_count = int(job.get("restartCount") or 0) + int(restarted)
        if scanner is None:
            preferences = _preferences_from_raw_values(projection.preference_values)
            folder_config = monitor_folder_config(dict(folder), preferences=preferences)
            scanner = StreamingDirectoryScanner(
                Path(str(job.get("rootPath") or "")), folder_config
            )
            self._scanners[job_id] = scanner
            self._scan_progress_state[job_id] = (
                monotonic(),
                counters["filesScanned"],
            )
            events.append(
                prepare_system_event(
                    source="import",
                    action="scan.started",
                    target_type="importScanJob",
                    target_id=job_id,
                    message="开始扫描监控文件夹",
                    metadata={
                        "rootPath": str(job.get("rootPath") or ""),
                        "trigger": str(job.get("trigger") or ""),
                    },
                )
            )

        scan_slice = scanner.next_slice(candidate_limit=min(500, remaining_capacity))
        sources = prepare_scan_sources(scan_slice.candidates)
        with self._session() as db:
            candidate_projection = load_scan_candidate_projection(
                db,
                sources,
                monitor_folder_id=str(folder["id"]),
            )
        checkpoint_at = db_timestamp()
        candidate_batch = prepare_scan_candidate_batch(
            sources,
            candidate_projection,
            monitor_folder_id=str(folder["id"]),
            now_ms=now_timestamp_ms(),
            now=checkpoint_at,
        )
        batch = candidate_batch.result
        counters["directoriesScanned"] += scan_slice.directories_scanned
        counters["filesScanned"] += scan_slice.files_scanned
        counters["candidatesFound"] += scan_slice.candidates_found
        counters["queuedCount"] += batch.queued_count
        counters["skippedCount"] += scan_slice.skipped_count + batch.cached_count
        counters["errorCount"] += len(scan_slice.errors)
        for reason, count in scan_slice.ignored_reason_counts.items():
            reasons[reason] = int(reasons.get(reason, 0)) + count
        samples.extend(
            error.to_storage()
            for error in scan_slice.errors[: max(0, 100 - len(samples))]
        )
        samples = samples[:100]

        progress_state = self._scan_progress_state.get(job_id)
        progress_due = False
        if progress_state is not None:
            last_progress_at, last_progress_files = progress_state
            progress_due = (
                monotonic() - last_progress_at >= 30
                or counters["filesScanned"] - last_progress_files >= 100_000
            )
        if progress_due and not scan_slice.completed:
            events.append(
                prepare_system_event(
                    source="import",
                    action="scan.progress",
                    target_type="importScanJob",
                    target_id=job_id,
                    message="监控文件夹扫描进行中",
                    metadata={
                        "filesScanned": counters["filesScanned"],
                        "candidatesFound": counters["candidatesFound"],
                        "queued": counters["queuedCount"],
                        "skipped": counters["skippedCount"],
                        "errorCount": counters["errorCount"],
                    },
                )
            )

        job_values: dict[str, object] = {
            "directories_scanned": counters["directoriesScanned"],
            "files_scanned": counters["filesScanned"],
            "candidates_found": counters["candidatesFound"],
            "queued_count": counters["queuedCount"],
            "skipped_count": counters["skippedCount"],
            "error_count": counters["errorCount"],
            "ignored_reason_counts": reasons,
            "error_samples": samples,
            "heartbeat_at": checkpoint_at,
            "updated_at": checkpoint_at,
            "restart_count": restart_count,
            "started_at": started_at,
        }
        disposition = "release"
        if scan_slice.completed:
            job_values.update(status="COMPLETED", finished_at=checkpoint_at)
            disposition = "complete"
            events.append(
                prepare_system_event(
                    source="import",
                    action="scan.completed",
                    level="warning" if counters["errorCount"] else "info",
                    target_type="importScanJob",
                    target_id=job_id,
                    message="监控文件夹扫描完成",
                    metadata={
                        "rootPath": str(job.get("rootPath") or ""),
                        "filesScanned": counters["filesScanned"],
                        "candidatesFound": counters["candidatesFound"],
                        "queued": counters["queuedCount"],
                        "skipped": counters["skippedCount"],
                        "errorCount": counters["errorCount"],
                        "ignoredReasonCounts": reasons,
                    },
                )
            )
        self._persist_scan_checkpoint(
            PreparedScanCheckpoint(
                job_id=job_id,
                work_item_id=work_item.id,
                job_values=job_values,
                work_disposition=disposition,
                work_available_at=checkpoint_at,
                candidate_batch=candidate_batch,
                events=tuple(events),
            )
        )
        if scan_slice.completed:
            self._close_scanner(job_id)
        elif progress_due:
            self._scan_progress_state[job_id] = (
                monotonic(),
                counters["filesScanned"],
            )
        return True

    def _close_scanner(self, job_id: str) -> None:
        scanner = self._scanners.pop(job_id, None)
        self._scan_progress_state.pop(job_id, None)
        if scanner is not None:
            scanner.close()

    def _close_inactive_scanners(self) -> None:
        if not self._scanners:
            return
        with self._session() as db:
            active_ids = set(
                db.scalars(
                    select(ImportScanJob.id).where(
                        ImportScanJob.id.in_(tuple(self._scanners)),
                        ImportScanJob.status.in_(("PENDING", "RUNNING")),
                    )
                ).all()
            )
        for job_id in set(self._scanners) - active_ids:
            self._close_scanner(job_id)

    def clear_records(self) -> int:
        with self._session() as db:
            persistent_work_queue.clear_work_queue(db)
            count = clear_import_queue_records(db)
        for scanner in self._scanners.values():
            scanner.close()
        self._scanners.clear()
        self._scan_progress_state.clear()
        return count

    def run_bounded_maintenance(self) -> int:
        self._close_inactive_scanners()
        with self._session() as db:
            projection = persistent_work_queue.load_import_queue_maintenance_projection(
                db,
                reconcile_limit=500,
                source_key_limit=500,
            )
        prepared = persistent_work_queue.prepare_import_queue_maintenance(
            projection,
            now=db_timestamp(),
        )
        with self._session() as db:
            changed = persistent_work_queue.write_prepared_import_queue_maintenance(
                db,
                prepared,
            )
            commit_import_checkpoint(db)
        return changed

    def shutdown(self) -> None:
        for scanner in self._scanners.values():
            scanner.close()
        self._scanners.clear()
        self._scan_progress_state.clear()


__all__ = [
    "IgnoredImportSource",
    "ImportIgnoreReason",
    "ImportWorkerRuntime",
    "MonitorFolderConfig",
    "ScanSummary",
    "StreamingDirectoryScanner",
    "cancel_import_scan_job",
    "claim_next_import_task",
    "clear_import_queue_records",
    "execute_recoverable_import_deletion",
    "fail_claimed_import_task",
    "get_import_scan_job",
    "import_file_ignore_reason",
    "import_http_store",
    "import_managed_book",
    "import_queue_at_high_watermark",
    "import_source_already_known",
    "import_source_meets_minimum_size",
    "is_proven_audio_bundle_directory",
    "library_repository",
    "list_import_scan_jobs",
    "load_persisted_scan_requests",
    "load_known_import_paths",
    "monitor_folder_config",
    "monitor_repository",
    "execute_import_enqueue_write",
    "load_import_enqueue_command_projection",
    "load_import_volume_deletion",
    "prepare_import_enqueue_command",
    "prepare_import_enqueue_write",
    "persist_import_events",
    "persist_import_monitor_folder_create",
    "persist_import_monitor_folder_delete",
    "persist_import_monitor_folder_update",
    "persist_import_enqueue_write",
    "persist_import_queue_operation_checkpoint",
    "persist_import_rescan_completion",
    "persist_import_scan_requests",
    "persist_import_task_retry",
    "persist_terminal_import_tasks_clear",
    "persist_watched_import_shelf_link",
    "process_import_task",
    "recover_interrupted_import_deletions",
    "recover_stale_import_tasks",
    "save_uploaded_files",
    "scan_directory_for_imports",
    "should_ignore_file",
    "should_ignore_path",
    "stage_import_events",
    "task_repository",
]
