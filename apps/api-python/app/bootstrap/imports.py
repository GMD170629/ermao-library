"""Import capability composition root."""

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.modules.imports.public import commit_import_checkpoint
from app.modules.imports.infrastructure import library_queries as library_repository
from app.modules.imports.infrastructure import monitor as monitor_repository
from app.modules.imports.infrastructure import tasks as task_repository
from app.modules.imports.infrastructure import import_http as import_http_store
from app.modules.imports.infrastructure import import_records
from app.modules.imports.infrastructure.directory_scan import (
    MonitorFolderConfig,
    ScanSummary,
    is_proven_audio_bundle_directory,
    monitor_folder_config,
    scan_directory_for_imports,
    should_ignore_file,
    should_ignore_path,
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
) -> tuple[dict[str, Any], bool]:
    return task_repository.stage_import_task(
        db,
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
) -> tuple[dict[str, Any], bool]:
    task, created = stage_import_task(
        db,
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
    if created:
        commit_import_checkpoint(db)
    return task, created


__all__ = [
    "enqueue_import_task",
    "import_http_store",
    "import_records",
    "is_proven_audio_bundle_directory",
    "library_repository",
    "load_known_import_paths",
    "MonitorFolderConfig",
    "monitor_repository",
    "monitor_folder_config",
    "scan_directory_for_imports",
    "ScanSummary",
    "should_ignore_file",
    "should_ignore_path",
    "task_repository",
    "stage_import_task",
]
