"""Import capability composition root."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.modules.imports.application.claim import (
    claim_next_import_task as claim_next_import_task_command,
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
    enqueue_import_path,
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
from app.modules.imports.infrastructure import import_http as import_http_store
from app.modules.imports.infrastructure import library_queries as library_repository
from app.modules.imports.infrastructure import monitor as monitor_repository
from app.modules.imports.infrastructure import tasks as task_repository
from app.modules.imports.infrastructure.deletion_files import LocalImportDeletionFiles
from app.modules.imports.infrastructure.directory_scan import (
    MonitorFolderConfig,
    ScanSummary,
    is_proven_audio_bundle_directory,
    monitor_folder_config,
    scan_directory_for_imports,
    should_ignore_file,
    should_ignore_path,
)
from app.modules.imports.infrastructure.managed_pipeline import SessionImportPipeline
from app.modules.imports.infrastructure.source_probe import LocalImportSourceProbe
from app.modules.imports.infrastructure.task_store import SqlAlchemyImportTaskStore
from app.modules.imports.infrastructure.uow import SqlAlchemyImportUnitOfWork
from app.modules.imports.infrastructure.uploaded_file_publication import (
    AtomicUploadedFilePublisher,
)


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
) -> tuple[ImportTaskDTO, bool]:
    store = SqlAlchemyImportTaskStore(db)
    return enqueue_import_path(
        store,
        SqlAlchemyImportUnitOfWork(db),
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


class ImportWorkerRuntime:
    """Session-owning facade used by the thin persistent import worker loop."""

    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
    ) -> None:
        self._db_factory = db_factory
        self._settings = settings

    @contextmanager
    def _session(self) -> Iterator[Session]:
        with self._db_factory() as db:
            yield db

    def recover(self) -> int:
        with self._session() as db:
            recover_interrupted_import_deletions(db, self._settings)
            return recover_stale_import_tasks(db)

    def claim(self, worker_id: str, lease_seconds: int) -> ImportTaskDTO | None:
        with self._session() as db:
            return claim_next_import_task(db, worker_id, lease_seconds)

    def process(self, task: ImportTaskDTO) -> ImportResult:
        with self._session() as db:
            return process_import_task(db, self._settings, task)

    def fail(self, task: ImportTaskDTO, error: BaseException) -> bool:
        with self._session() as db:
            return fail_claimed_import_task(db, task, error)


__all__ = [
    "ImportWorkerRuntime",
    "MonitorFolderConfig",
    "ScanSummary",
    "claim_next_import_task",
    "enqueue_import_task",
    "execute_recoverable_import_deletion",
    "fail_claimed_import_task",
    "import_http_store",
    "import_managed_book",
    "is_proven_audio_bundle_directory",
    "library_repository",
    "load_known_import_paths",
    "monitor_folder_config",
    "monitor_repository",
    "process_import_task",
    "recover_interrupted_import_deletions",
    "recover_stale_import_tasks",
    "save_uploaded_files",
    "scan_directory_for_imports",
    "should_ignore_file",
    "should_ignore_path",
    "stage_import_task",
    "task_repository",
]
