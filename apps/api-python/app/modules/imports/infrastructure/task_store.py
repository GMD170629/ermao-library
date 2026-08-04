"""SQLAlchemy ImportTaskStore adapter."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import MonitorFolder
from app.modules.imports.application.dto import ImportTaskDTO, StageImportCommand
from app.modules.imports.infrastructure import tasks as task_rows
from app.modules.imports.infrastructure.task_mapper import import_task_dto_from_row
from app.modules.system.infrastructure.events import record_system_event


class SqlAlchemyImportTaskStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def stage(self, command: StageImportCommand) -> tuple[ImportTaskDTO, bool]:
        media_kind_policy = command.media_kind_policy
        if media_kind_policy is None and command.monitor_folder_id is not None:
            media_kind_policy = self._db.scalar(
                select(MonitorFolder.media_kind_policy).where(
                    MonitorFolder.id == command.monitor_folder_id
                )
            )
        row, created = task_rows.stage_import_task(
            self._db,
            command.source_path,
            origin=command.origin,
            original_name=command.original_name,
            requested_title=command.requested_title,
            requested_author=command.requested_author,
            monitor_folder_id=command.monitor_folder_id,
            media_kind_policy=str(media_kind_policy or "MIXED"),
            message=command.message,
            allow_terminal_requeue=command.allow_terminal_requeue,
        )
        return import_task_dto_from_row(row), created

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
        )

    def stage_failure_event(
        self,
        task: ImportTaskDTO,
        *,
        error_summary: str,
        now: int,
    ) -> None:
        record_system_event(
            self._db,
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
                "monitorFolderId": task.monitor_folder_id,
                "error": error_summary,
                "finishedAt": now,
            },
        )

    def monitor_folder_exists(self, monitor_folder_id: str) -> bool:
        return (
            self._db.scalar(
                select(MonitorFolder.id)
                .where(MonitorFolder.id == monitor_folder_id)
                .limit(1)
            )
            is not None
        )

    def link_work_to_monitor_shelf(
        self,
        monitor_folder_id: str | None,
        work_id: str,
        *,
        created_at: int,
    ) -> None:
        task_rows.link_imported_work_to_monitor_shelf(
            self._db,
            monitor_folder_id,
            work_id,
            created_at=created_at,
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
