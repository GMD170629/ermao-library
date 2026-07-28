"""SQLAlchemy persistence for download-task HTTP use cases."""

from __future__ import annotations

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.models.common import db_timestamp
from app.models.import_pipeline import DownloadTask
from app.modules.download.application.dto import (
    CreateDownloadTask,
    DownloadTaskDTO,
    UpdateDownloadTask,
)
from app.modules.download.application.ports import DownloadTaskRepository


def _to_dto(task: DownloadTask) -> DownloadTaskDTO:
    return DownloadTaskDTO(
        id=task.id,
        source_id=task.source_id,
        search_record_id=task.search_record_id,
        book_id=task.book_id,
        task_type=task.task_type,
        status=task.status,
        display_name=task.display_name,
        remote_ref=task.remote_ref,
        save_path=task.save_path,
        file_path=task.file_path,
        error_message=task.error_message,
        progress=task.progress,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


class SqlAlchemyDownloadTaskRepository(DownloadTaskRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def _has_table(self) -> bool:
        return inspect(self._session.connection()).has_table("DownloadTask")

    def list_recent(self, *, limit: int) -> list[DownloadTaskDTO]:
        if not self._has_table():
            return []
        tasks = self._session.scalars(
            select(DownloadTask)
            .order_by(DownloadTask.created_at.desc(), DownloadTask.id.desc())
            .limit(limit)
        ).all()
        return [_to_dto(task) for task in tasks]

    def get(self, task_id: str) -> DownloadTaskDTO | None:
        if not self._has_table():
            return None
        task = self._session.get(DownloadTask, task_id)
        return _to_dto(task) if task is not None else None

    def create(self, command: CreateDownloadTask) -> DownloadTaskDTO:
        task = DownloadTask(
            id=command.id,
            source_id=command.source_id,
            search_record_id=command.search_record_id,
            book_id=command.book_id,
            task_type=command.task_type,
            status=command.status,
            display_name=command.display_name,
            remote_ref=command.remote_ref,
            save_path=command.save_path,
            file_path=command.file_path,
            error_message=command.error_message,
            progress=command.progress,
        )
        self._session.add(task)
        self._session.flush()
        return _to_dto(task)

    def update(
        self,
        task_id: str,
        changes: UpdateDownloadTask,
    ) -> DownloadTaskDTO | None:
        if not self._has_table():
            return None
        task = self._session.get(DownloadTask, task_id)
        if task is None:
            return None
        values = {
            "type": ("task_type", changes.task_type),
            "status": ("status", changes.status),
            "displayName": ("display_name", changes.display_name),
            "savePath": ("save_path", changes.save_path),
            "filePath": ("file_path", changes.file_path),
            "errorMessage": ("error_message", changes.error_message),
            "progress": ("progress", changes.progress),
            "remoteRef": ("remote_ref", changes.remote_ref),
        }
        for field in changes.changed_fields:
            mapped = values.get(field)
            if mapped is not None:
                attribute, value = mapped
                setattr(task, attribute, value)
        task.updated_at = db_timestamp()
        self._session.flush()
        return _to_dto(task)

    def delete(self, task_id: str) -> bool:
        if not self._has_table():
            return False
        task = self._session.get(DownloadTask, task_id)
        if task is None:
            return False
        self._session.delete(task)
        self._session.flush()
        return True


def list_download_tasks_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[dict[str, object]], int]:
    if not inspect(db.connection()).has_table("DownloadTask"):
        return [], 0
    filters = []
    normalized = str(status or "").strip().lower()
    if normalized and normalized != "all":
        filters.append(DownloadTask.status == normalized)
    statement = select(DownloadTask).where(*filters)
    tasks = db.scalars(
        statement.order_by(DownloadTask.created_at.desc(), DownloadTask.id.desc())
        .limit(page_size)
        .offset((max(1, page) - 1) * page_size)
    ).all()
    return [_to_dto(task).to_legacy_dict() for task in tasks], len(tasks)
