"""Download capability composition root."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.bootstrap.readable_resource_pipeline import continue_library_import
from app.bootstrap.system import (
    prepare_settings_write,
    write_prepared_settings,
    write_prepared_system_events,
)
from app.models.common import db_timestamp
from app.models.library import Library
from app.modules.download.application.dto import (
    CreateDownloadTask,
    DownloadTaskDTO,
    UpdateDownloadTask,
)
from app.modules.download.infrastructure.download_http import (
    SqlAlchemyDownloadTaskRepository,
    download_task_to_dto,
    execute_download_task_delete,
    execute_download_task_update,
    prepare_download_task_create,
    prepare_download_task_delete,
    prepare_download_task_update,
    write_prepared_download_task_create,
)
from app.modules.download.infrastructure.tasks import (
    entity_record,
    execute_download_task_row_update,
    prepare_claim_download_task,
    prepare_download_task_state_update,
    prepare_mark_download_task_importing,
)
from app.modules.download.infrastructure.tasks import (
    list_enabled_libraries as _list_enabled_libraries,
)
from app.modules.download.public import DownloadWriteTransaction
from app.modules.imports.application.readable_resource.continue_import import (
    ContinueImportResult,
)
from app.modules.system.domain.events import PreparedSystemEvent


def list_download_tasks(db: Session, *, limit: int = 1000) -> list[DownloadTaskDTO]:
    return SqlAlchemyDownloadTaskRepository(db).list_recent(limit=limit)


def list_enabled_libraries(db: Session) -> list[dict[str, Any]]:
    return _list_enabled_libraries(db)


def get_download_task(db: Session, task_id: str) -> DownloadTaskDTO | None:
    return SqlAlchemyDownloadTaskRepository(db).get(task_id)


def create_download_task(
    db: Session,
    command: CreateDownloadTask,
) -> DownloadTaskDTO:
    prepared = prepare_download_task_create(command, timestamp=db_timestamp())
    with DownloadWriteTransaction(db):
        write_prepared_download_task_create(db, prepared)
    return prepared.result


def write_download_task(
    db: Session,
    command: CreateDownloadTask,
) -> DownloadTaskDTO:
    """SQL-only persistence port for a caller-owned transaction."""

    return SqlAlchemyDownloadTaskRepository(db).create(command)


def update_download_task(
    db: Session,
    task_id: str,
    changes: UpdateDownloadTask,
) -> DownloadTaskDTO | None:
    statement = prepare_download_task_update(
        task_id,
        changes,
        timestamp=db_timestamp(),
    )
    with DownloadWriteTransaction(db):
        updated = execute_download_task_update(db, statement)
    return download_task_to_dto(updated) if updated is not None else None


def write_download_task_update(
    db: Session,
    task_id: str,
    changes: UpdateDownloadTask,
) -> DownloadTaskDTO | None:
    return SqlAlchemyDownloadTaskRepository(db).update(task_id, changes)


def delete_download_task(db: Session, task_id: str) -> bool:
    statement = prepare_download_task_delete(task_id)
    with DownloadWriteTransaction(db):
        deleted = execute_download_task_delete(db, statement)
    return deleted


def write_download_task_delete(db: Session, task_id: str) -> bool:
    return SqlAlchemyDownloadTaskRepository(db).delete(task_id)


def create_download_task_command(
    db: Session,
    command: CreateDownloadTask,
    *,
    last_target_path: str,
    event: PreparedSystemEvent,
) -> DownloadTaskDTO:
    prepared_task = prepare_download_task_create(command, timestamp=db_timestamp())
    prepared_settings = prepare_settings_write(
        {"library.lastDownloadTargetPath": last_target_path}
    )
    with DownloadWriteTransaction(db):
        write_prepared_download_task_create(db, prepared_task)
        write_prepared_settings(db, prepared_settings)
        write_prepared_system_events(db, (event,))
    return prepared_task.result


def delete_download_task_command(
    db: Session, task_id: str, *, event: PreparedSystemEvent
) -> bool:
    statement = prepare_download_task_delete(task_id)
    with DownloadWriteTransaction(db):
        deleted = execute_download_task_delete(db, statement)
        if deleted:
            write_prepared_system_events(db, (event,))
    return deleted


def update_download_task_command(
    db: Session,
    task_id: str,
    changes: UpdateDownloadTask,
    *,
    event: PreparedSystemEvent,
) -> DownloadTaskDTO | None:
    statement = prepare_download_task_update(
        task_id,
        changes,
        timestamp=db_timestamp(),
    )
    with DownloadWriteTransaction(db):
        task_row = execute_download_task_update(db, statement)
        if task_row is not None:
            write_prepared_system_events(db, (event,))
    return download_task_to_dto(task_row) if task_row is not None else None


def claim_download_task_command(
    db: Session, task_id: str, *, timestamp: datetime
) -> dict[str, Any] | None:
    statement = prepare_claim_download_task(task_id, now=timestamp)
    with DownloadWriteTransaction(db):
        task = execute_download_task_row_update(db, statement)
    return entity_record(task) if task is not None else None


def finalize_download_task_command(
    db: Session,
    task_id: str,
    *,
    values: dict[str, object],
    event: PreparedSystemEvent,
) -> dict[str, Any] | None:
    statement = prepare_download_task_state_update(task_id, values)
    with DownloadWriteTransaction(db):
        task = execute_download_task_row_update(db, statement)
        write_prepared_system_events(db, (event,))
    return entity_record(task) if task is not None else None


def continue_download_import_command(
    db: Session,
    *,
    task_id: str,
    library_id: str | None,
) -> ContinueImportResult:
    if library_id is None:
        raise ValueError("downloaded file is not owned by a library")
    library = db.get(Library, library_id)
    if library is None or not library.enabled:
        raise ValueError("download target library is unavailable")
    mark_importing_statement = prepare_mark_download_task_importing(
        task_id,
        updated_at=db_timestamp(),
    )
    result = continue_library_import(db, library_id)
    with DownloadWriteTransaction(db):
        db.execute(mark_importing_statement)
    return result


__all__ = [
    "claim_download_task_command",
    "continue_download_import_command",
    "create_download_task",
    "create_download_task_command",
    "delete_download_task",
    "delete_download_task_command",
    "finalize_download_task_command",
    "get_download_task",
    "list_download_tasks",
    "list_enabled_libraries",
    "update_download_task",
    "update_download_task_command",
    "write_download_task",
    "write_download_task_delete",
    "write_download_task_update",
]
