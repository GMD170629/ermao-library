"""Import capability composition root."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from time import monotonic

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.models.common import db_timestamp
from app.models.import_pipeline import ImportScanJob, ImportTask
from app.models.settings import MonitorFolder
from app.modules.imports.application.claim import (
    claim_next_import_task as claim_next_import_task_command,
)
from app.modules.imports.application.clear_queue import (
    clear_import_queue as clear_import_queue_command,
)
from app.modules.imports.application.deletion import (
    FileCleanupResult,
    execute_import_deletion,
)
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    ImportRuntimeConfig,
    ImportTaskDTO,
)
from app.modules.imports.application.enqueue import (
    stage_import_path,
)
from app.modules.imports.application.fail import (
    fail_claimed_import_task as fail_claimed_import_task_command,
)
from app.modules.imports.application.process import (
    process_import_task as process_import_task_command,
)
from app.modules.imports.application.recover import (
    recover_stale_import_tasks as recover_stale_import_tasks_command,
)
from app.modules.imports.application.save_uploaded_files import (
    SavedUploadFile,
    SaveUploadedFiles,
    SaveUploadedFilesCommand,
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
from app.modules.imports.infrastructure.managed_pipeline import SessionImportPipeline
from app.modules.imports.infrastructure.queue_maintenance import (
    SqlAlchemyImportQueueMaintenanceStore,
)
from app.modules.imports.infrastructure.scan_batch_store import (
    stage_scan_candidate_batch,
)
from app.modules.imports.infrastructure.source_probe import LocalImportSourceProbe
from app.modules.imports.infrastructure.streaming_scan import StreamingDirectoryScanner
from app.modules.imports.infrastructure.task_store import SqlAlchemyImportTaskStore
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)
from app.modules.imports.infrastructure.work_queue import ensure_import_work_item
from app.modules.system.infrastructure.events import record_system_event
from app.services.import_preferences import load_import_preferences


def import_managed_book(
    db: Session, settings: Settings, options: ImportOptions
) -> ImportResult:
    """Session-bound composition wrapper for media import."""

    return SessionImportPipeline(db, settings).import_managed_book(
        _runtime_config(settings), options
    )


def save_uploaded_files(
    command: SaveUploadedFilesCommand,
) -> tuple[SavedUploadFile, ...]:
    """Compose the browser-upload save use case with local atomic publication."""

    return SaveUploadedFiles(AtomicUploadedFilePublisher()).execute(command)


def _runtime_config(settings: Settings) -> ImportRuntimeConfig:
    return ImportRuntimeConfig(
        storage_root=settings.resolved_storage_root,
        monitor_root=settings.resolved_monitor_root,
        audiobook_max_file_bytes=settings.audiobook_max_file_bytes,
    )


def load_known_import_paths(db: Session) -> set[Path]:
    return monitor_repository.load_known_import_paths(db)


def stage_import_task(
    db: Session,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    work_id: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[ImportTaskDTO, bool]:
    store = SqlAlchemyImportTaskStore(db)
    return stage_import_path(
        store,
        source_path,
        origin=origin,
        original_name=original_name,
        requested_title=requested_title,
        requested_author=requested_author,
        work_id=work_id,
        monitor_folder_id=monitor_folder_id,
        message=message,
        allow_terminal_requeue=allow_terminal_requeue,
    )


def enqueue_import_task(
    db: Session,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    work_id: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
    available_at: datetime | None = None,
) -> tuple[ImportTaskDTO, bool]:
    store = SqlAlchemyImportTaskStore(db)
    task, created = stage_import_path(
        store,
        source_path,
        origin=origin,
        original_name=original_name,
        requested_title=requested_title,
        requested_author=requested_author,
        work_id=work_id,
        monitor_folder_id=monitor_folder_id,
        message=message,
        allow_terminal_requeue=allow_terminal_requeue,
    )
    if created or task.status == "PENDING":
        row = db.get(ImportTask, task.id)
        if row is None:
            raise RuntimeError(f"staged import task {task.id} was not persisted")
        ensure_import_work_item(db, row, available_at=available_at)
        db.commit()
    return task, created


def schedule_import_scan_job(
    db: Session,
    *,
    monitor_folder_id: str,
    actor_user_id: str | None,
    root_path: Path,
    trigger: str,
    available_at: datetime | None = None,
) -> tuple[ImportScanJobDTO, bool]:
    job, created = persistent_work_queue.create_or_reuse_scan_job(
        db,
        monitor_folder_id=monitor_folder_id,
        actor_user_id=actor_user_id,
        root_path=root_path,
        trigger=trigger,
        available_at=available_at,
    )
    db.commit()
    return job, created


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
    db.commit()
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
    if settings.resolved_monitor_root is not None:
        monitor_roots.append(settings.resolved_monitor_root)
    files = LocalImportDeletionFiles(
        settings.resolved_storage_root,
        [settings.conversion_root, *monitor_roots],
    )
    return files.recover_pending(
        database_record_exists=lambda task_id: (
            import_http_store.get_import_task(db, task_id) is not None
        )
    )


def execute_recoverable_import_deletion(
    db: Session,
    settings: Settings,
    *,
    owner_id: str,
    paths: Sequence[str],
    monitor_roots: Sequence[Path],
    database_operation: Callable[[], object],
) -> tuple[object, FileCleanupResult]:
    files = LocalImportDeletionFiles(
        settings.resolved_storage_root,
        [settings.conversion_root, *monitor_roots],
    )
    return execute_import_deletion(
        SqlAlchemyImportUnitOfWork(db),
        files,
        owner_id,
        paths,
        database_operation,
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
    unit_of_work = SqlAlchemyImportUnitOfWork(db)
    pipeline = SessionImportPipeline(db, settings, unit_of_work)
    return process_import_task_command(
        store,
        unit_of_work,
        pipeline,
        _runtime_config(settings),
        task,
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
        with self._session() as db:
            recover_interrupted_import_deletions(db, self._settings)
            recovered = recover_stale_import_tasks(db)
            recovered += persistent_work_queue.recover_scan_work_items(db)
            recovered += persistent_work_queue.reconcile_existing_import_tasks(db)
            db.commit()
            return recovered

    def claim_work(
        self, worker_id: str, lease_seconds: int
    ) -> ImportWorkItemDTO | None:
        with self._session() as db:
            self._close_inactive_scanners(db)
            work = persistent_work_queue.claim_next_work_item(
                db,
                worker_id=worker_id,
                import_lease_seconds=lease_seconds,
            )
            db.commit()
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
            db.commit()
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
            db.commit()

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
                    db.commit()
            raise

    def _process_scan_once(self, work_item: ImportWorkItemDTO) -> bool:
        if work_item.scan_job_id is None:
            self.complete_work(work_item.id)
            return False
        with self._session() as db:
            job = db.get(ImportScanJob, work_item.scan_job_id)
            if job is None or job.status == "CANCELLED":
                persistent_work_queue.complete_work_item(db, work_item.id)
                db.commit()
                self._close_scanner(work_item.scan_job_id)
                return False
            active_imports = persistent_work_queue.active_import_work_count(db)
            remaining_capacity = (
                persistent_work_queue.IMPORT_WORK_HIGH_WATERMARK - active_imports
            )
            if remaining_capacity <= 0:
                persistent_work_queue.release_scan_work_item(db, work_item.id)
                db.commit()
                return False
            folder = (
                db.get(MonitorFolder, job.monitor_folder_id)
                if job.monitor_folder_id
                else None
            )
            if folder is None or not folder.enabled:
                self._fail_scan(
                    db,
                    job,
                    work_item.id,
                    "监控文件夹已删除或停用",
                )
                db.commit()
                self._close_scanner(job.id)
                return False
            scanner = self._scanners.get(job.id)
            if scanner is None:
                if work_item.attempts > 1:
                    job.directories_scanned = 0
                    job.files_scanned = 0
                    job.candidates_found = 0
                    job.queued_count = 0
                    job.skipped_count = 0
                    job.error_count = 0
                    job.ignored_reason_counts = {}
                    job.error_samples = []
                    job.restart_count += 1
                    job.started_at = db_timestamp()
                folder_config = monitor_folder_config(
                    {
                        "id": folder.id,
                        "rootPath": folder.root_path,
                        "shelfId": folder.shelf_id,
                        "ignoreHidden": folder.ignore_hidden,
                        "ignorePatterns": folder.ignore_patterns,
                        "minFileSizeBytes": folder.min_file_size_bytes,
                    },
                    preferences=load_import_preferences(db),
                )
                scanner = StreamingDirectoryScanner(Path(job.root_path), folder_config)
                self._scanners[job.id] = scanner
                self._scan_progress_state[job.id] = (monotonic(), job.files_scanned)
                record_system_event(
                    db,
                    source="import",
                    action="scan.started",
                    target_type="importScanJob",
                    target_id=job.id,
                    message="开始扫描监控文件夹",
                    metadata={"rootPath": job.root_path, "trigger": job.trigger},
                )
            scan_slice = scanner.next_slice(
                candidate_limit=min(500, remaining_capacity)
            )
            batch = stage_scan_candidate_batch(
                db,
                scan_slice.candidates,
                monitor_folder_id=folder.id,
            )
            queued = batch.queued_count
            cached = batch.cached_count
            job.directories_scanned += scan_slice.directories_scanned
            job.files_scanned += scan_slice.files_scanned
            job.candidates_found += scan_slice.candidates_found
            job.queued_count += queued
            job.skipped_count += scan_slice.skipped_count + cached
            job.error_count += len(scan_slice.errors)
            reasons = dict(job.ignored_reason_counts or {})
            for reason, count in scan_slice.ignored_reason_counts.items():
                reasons[reason] = int(reasons.get(reason, 0)) + count
            job.ignored_reason_counts = reasons
            samples = list(job.error_samples or [])
            samples.extend(
                error.to_storage()
                for error in scan_slice.errors[: max(0, 100 - len(samples))]
            )
            job.error_samples = samples[:100]
            job.heartbeat_at = db_timestamp()
            job.updated_at = db_timestamp()
            progress_state = self._scan_progress_state.get(job.id)
            if progress_state is not None:
                last_progress_at, last_progress_files = progress_state
                progress_due = (
                    monotonic() - last_progress_at >= 30
                    or job.files_scanned - last_progress_files >= 100_000
                )
                if progress_due and not scan_slice.completed:
                    record_system_event(
                        db,
                        source="import",
                        action="scan.progress",
                        target_type="importScanJob",
                        target_id=job.id,
                        message="监控文件夹扫描进行中",
                        metadata={
                            "filesScanned": job.files_scanned,
                            "candidatesFound": job.candidates_found,
                            "queued": job.queued_count,
                            "skipped": job.skipped_count,
                            "errorCount": job.error_count,
                        },
                    )
                    self._scan_progress_state[job.id] = (
                        monotonic(),
                        job.files_scanned,
                    )
            if scan_slice.completed:
                job.status = "COMPLETED"
                job.finished_at = db_timestamp()
                persistent_work_queue.complete_work_item(db, work_item.id)
                record_system_event(
                    db,
                    source="import",
                    action="scan.completed",
                    level="warning" if job.error_count else "info",
                    target_type="importScanJob",
                    target_id=job.id,
                    message="监控文件夹扫描完成",
                    metadata={
                        "rootPath": job.root_path,
                        "filesScanned": job.files_scanned,
                        "candidatesFound": job.candidates_found,
                        "queued": job.queued_count,
                        "skipped": job.skipped_count,
                        "errorCount": job.error_count,
                        "ignoredReasonCounts": reasons,
                    },
                )
                self._close_scanner(job.id)
            else:
                persistent_work_queue.release_scan_work_item(db, work_item.id)
            db.commit()
            return True

    def _fail_scan(
        self,
        db: Session,
        job: ImportScanJob,
        work_item_id: str,
        message: str,
    ) -> None:
        job.status = "FAILED"
        job.error_count += 1
        job.error_samples = [
            *list(job.error_samples or [])[:99],
            {"path": job.root_path, "error": message},
        ]
        job.finished_at = db_timestamp()
        job.updated_at = db_timestamp()
        persistent_work_queue.complete_work_item(db, work_item_id)
        record_system_event(
            db,
            source="import",
            action="scan.failed",
            level="error",
            target_type="importScanJob",
            target_id=job.id,
            message="监控文件夹扫描失败",
            metadata={"rootPath": job.root_path, "error": message},
        )

    def _close_scanner(self, job_id: str) -> None:
        scanner = self._scanners.pop(job_id, None)
        self._scan_progress_state.pop(job_id, None)
        if scanner is not None:
            scanner.close()

    def _close_inactive_scanners(self, db: Session) -> None:
        if not self._scanners:
            return
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
        with self._session() as db:
            self._close_inactive_scanners(db)
            reconciled = persistent_work_queue.reconcile_existing_import_tasks(
                db, limit=500
            )
            backfilled = persistent_work_queue.backfill_source_keys(db, limit=500)
            db.commit()
            return reconciled + backfilled

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
    "enqueue_import_task",
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
    "load_known_import_paths",
    "monitor_folder_config",
    "monitor_repository",
    "process_import_task",
    "recover_interrupted_import_deletions",
    "recover_stale_import_tasks",
    "save_uploaded_files",
    "scan_directory_for_imports",
    "schedule_import_scan_job",
    "should_ignore_file",
    "should_ignore_path",
    "stage_import_task",
    "task_repository",
]
