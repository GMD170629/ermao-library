"""Stage and enqueue import tasks."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.commands import commit_import_checkpoint
from app.modules.imports.application.dto import ImportTaskDTO, StageImportCommand
from app.modules.imports.application.ports import ImportTaskStore, ImportUnitOfWork


def stage_import_task(
    store: ImportTaskStore,
    command: StageImportCommand,
) -> tuple[ImportTaskDTO, bool]:
    return store.stage(command)


def enqueue_import_task(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    command: StageImportCommand,
) -> tuple[ImportTaskDTO, bool]:
    task, created = store.stage(command)
    if created:
        commit_import_checkpoint(unit_of_work)
    return task, created


def stage_import_path(
    store: ImportTaskStore,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[ImportTaskDTO, bool]:
    return stage_import_task(
        store,
        StageImportCommand(
            source_path=Path(source_path),
            origin=origin,
            original_name=original_name,
            requested_title=requested_title,
            requested_author=requested_author,
            monitor_folder_id=monitor_folder_id,
            message=message,
            allow_terminal_requeue=allow_terminal_requeue,
        ),
    )


def enqueue_import_path(
    store: ImportTaskStore,
    unit_of_work: ImportUnitOfWork,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[ImportTaskDTO, bool]:
    return enqueue_import_task(
        store,
        unit_of_work,
        StageImportCommand(
            source_path=Path(source_path),
            origin=origin,
            original_name=original_name,
            requested_title=requested_title,
            requested_author=requested_author,
            monitor_folder_id=monitor_folder_id,
            message=message,
            allow_terminal_requeue=allow_terminal_requeue,
        ),
    )
