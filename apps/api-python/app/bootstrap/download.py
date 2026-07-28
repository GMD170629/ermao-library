"""Download capability composition root."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.modules.download.application.dto import (
    CreateDownloadTask,
    DownloadTaskDTO,
    UpdateDownloadTask,
)
from app.modules.download.infrastructure.download_http import (
    SqlAlchemyDownloadTaskRepository,
)
from app.modules.download.public import execute_download_write


def list_download_tasks(db: Session, *, limit: int = 1000) -> list[DownloadTaskDTO]:
    return SqlAlchemyDownloadTaskRepository(db).list_recent(limit=limit)


def get_download_task(db: Session, task_id: str) -> DownloadTaskDTO | None:
    return SqlAlchemyDownloadTaskRepository(db).get(task_id)


def create_download_task(
    db: Session,
    command: CreateDownloadTask,
) -> DownloadTaskDTO:
    repository = SqlAlchemyDownloadTaskRepository(db)
    return execute_download_write(db, lambda: repository.create(command))


def update_download_task(
    db: Session,
    task_id: str,
    changes: UpdateDownloadTask,
) -> DownloadTaskDTO | None:
    repository = SqlAlchemyDownloadTaskRepository(db)
    return execute_download_write(db, lambda: repository.update(task_id, changes))


def delete_download_task(db: Session, task_id: str) -> bool:
    repository = SqlAlchemyDownloadTaskRepository(db)
    return execute_download_write(db, lambda: repository.delete(task_id))


__all__ = [
    "create_download_task",
    "delete_download_task",
    "get_download_task",
    "list_download_tasks",
    "update_download_task",
]
