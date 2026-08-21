"""SQLAlchemy persistence for download-task HTTP use cases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Delete, Insert, Update

from app.models.common import db_timestamp
from app.models.import_pipeline import DownloadTask
from app.modules.download.application.dto import (
    CreateDownloadTask,
    DownloadTaskDTO,
    UpdateDownloadTask,
)
from app.modules.download.application.ports import DownloadTaskRepository


def download_task_to_dto(task: DownloadTask) -> DownloadTaskDTO:
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


@dataclass(frozen=True)
class PreparedDownloadTaskCreate:
    statement: Insert
    result: DownloadTaskDTO


def prepare_download_task_create(
    command: CreateDownloadTask,
    *,
    timestamp: datetime,
) -> PreparedDownloadTaskCreate:
    result = DownloadTaskDTO(
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
        created_at=timestamp,
        updated_at=timestamp,
    )
    return PreparedDownloadTaskCreate(
        statement=insert(DownloadTask).values(
            id=result.id,
            source_id=result.source_id,
            search_record_id=result.search_record_id,
            book_id=result.book_id,
            task_type=result.task_type,
            status=result.status,
            display_name=result.display_name,
            remote_ref=result.remote_ref,
            save_path=result.save_path,
            file_path=result.file_path,
            error_message=result.error_message,
            progress=result.progress,
            created_at=result.created_at,
            updated_at=result.updated_at,
        ),
        result=result,
    )


def write_prepared_download_task_create(
    db: Session,
    prepared: PreparedDownloadTaskCreate,
) -> None:
    db.execute(prepared.statement)


def prepare_download_task_update(
    task_id: str,
    changes: UpdateDownloadTask,
    *,
    timestamp: datetime,
) -> Update:
    field_mapping = {
        "type": ("task_type", changes.task_type),
        "status": ("status", changes.status),
        "displayName": ("display_name", changes.display_name),
        "savePath": ("save_path", changes.save_path),
        "filePath": ("file_path", changes.file_path),
        "errorMessage": ("error_message", changes.error_message),
        "progress": ("progress", changes.progress),
        "remoteRef": ("remote_ref", changes.remote_ref),
    }
    patch = {
        attribute: value
        for field in changes.changed_fields
        if (mapped := field_mapping.get(field)) is not None
        for attribute, value in (mapped,)
    }
    patch["updated_at"] = timestamp
    return (
        update(DownloadTask)
        .where(DownloadTask.id == task_id)
        .values(**patch)
        .returning(DownloadTask)
    )


def execute_download_task_update(
    db: Session,
    statement: Update,
) -> DownloadTask | None:
    return db.execute(statement).scalar_one_or_none()


def prepare_download_task_delete(task_id: str) -> Delete:
    return delete(DownloadTask).where(DownloadTask.id == task_id)


def execute_download_task_delete(db: Session, statement: Delete) -> bool:
    result = db.execute(statement)
    return bool(result.rowcount)


class SqlAlchemyDownloadTaskRepository(DownloadTaskRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_recent(self, *, limit: int) -> list[DownloadTaskDTO]:
        tasks = self._session.scalars(
            select(DownloadTask)
            .order_by(DownloadTask.created_at.desc(), DownloadTask.id.desc())
            .limit(limit)
        ).all()
        return [download_task_to_dto(task) for task in tasks]

    def get(self, task_id: str) -> DownloadTaskDTO | None:
        task = self._session.get(DownloadTask, task_id)
        return download_task_to_dto(task) if task is not None else None

    def create(self, command: CreateDownloadTask) -> DownloadTaskDTO:
        prepared = prepare_download_task_create(command, timestamp=db_timestamp())
        write_prepared_download_task_create(self._session, prepared)
        return prepared.result

    def update(
        self,
        task_id: str,
        changes: UpdateDownloadTask,
    ) -> DownloadTaskDTO | None:
        statement = prepare_download_task_update(
            task_id,
            changes,
            timestamp=db_timestamp(),
        )
        task = execute_download_task_update(self._session, statement)
        if task is None:
            return None
        return download_task_to_dto(task)

    def delete(self, task_id: str) -> bool:
        statement = prepare_download_task_delete(task_id)
        return execute_download_task_delete(self._session, statement)


def list_download_tasks_page(
    db: Session,
    *,
    page: int,
    page_size: int,
    status: str | None = None,
) -> tuple[list[dict[str, object]], int]:
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
    return [download_task_to_dto(task).to_legacy_dict() for task in tasks], len(tasks)
