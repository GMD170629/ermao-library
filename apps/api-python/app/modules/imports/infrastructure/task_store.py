"""SQLAlchemy ImportTaskStore adapter."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import Library
from app.modules.imports.application.dto import ImportTaskDTO
from app.modules.imports.infrastructure import tasks as task_rows
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row
from app.services.system_events import (
    prepare_system_event,
    write_prepared_system_events,
)


class SqlAlchemyImportTaskStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def recover_stale(self, *, now: int, message: str) -> int:
        return task_rows.recover_stale_import_tasks(self._db, now=now, message=message)

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: int,
        now: int,
    ) -> ImportTaskDTO | None:
        row = task_rows.claim_next_import_task(
            self._db,
            worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )
        if row is None:
            return None
        return import_task_dto_from_row(row)

    def fail_claimed(
        self,
        task: ImportTaskDTO,
        *,
        error_code: str,
        error_summary: str,
        message: str,
        retryable: bool,
        now: int,
    ) -> bool:
        return task_rows.fail_claimed_import_task_row(
            self._db,
            task.id,
            error_code=error_code,
            error_summary=error_summary,
            message=message,
            retryable=retryable,
            now=now,
            expected_lease_owner=task.lease_owner,
        )

    def stage_failure_event(
        self,
        task: ImportTaskDTO,
        *,
        error_summary: str,
        now: int,
    ) -> None:
        prepared_event = prepare_system_event(
            source="import",
            action="import.failed",
            level="error",
            target_type="importTask",
            target_id=task.id,
            message=f"导入失败：{task.original_name or Path(task.source_path).name}",
            metadata={
                "sourcePath": task.source_path,
                "originalName": task.original_name,
                "origin": task.origin,
                "libraryId": task.library_id,
                "error": error_summary,
                "finishedAt": now,
            },
        )
        write_prepared_system_events(self._db, [prepared_event])

    def library_exists(self, library_id: str) -> bool:
        return (
            self._db.scalar(
                select(Library.id)
                .where(Library.id == library_id)
                .limit(1)
            )
            is not None
        )

    def mark_download_completed(
        self,
        *,
        source_path: str,
        book_id: str,
        updated_at: int,
    ) -> None:
        task_rows.mark_download_task_completed_for_import(
            self._db,
            source_path=source_path,
            book_id=book_id,
            updated_at=updated_at,
        )
