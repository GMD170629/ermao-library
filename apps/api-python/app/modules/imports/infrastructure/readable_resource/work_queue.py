"""Single-consumer LibraryImportTask queue for ADR 0018 ContinueImport."""

from __future__ import annotations

from datetime import datetime

from typing import cast

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.common import cuid
from app.modules.imports.application.readable_resource.ports import (
    ImportTaskKind,
    ImportTaskState,
    LibraryImportTaskRecord,
    WORKER_INTERRUPTED,
    WorkQueuePort,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.domain.readable_resource_states import AssetRole


class SqlAlchemyReadableResourceWorkQueue(WorkQueuePort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        kind: ImportTaskKind,
        library_id: str,
        resource_id: str | None = None,
        source_node_id: str | None = None,
        role: AssetRole | None = None,
    ) -> LibraryImportTaskRecord:
        row = LibraryImportTask(
            id=cuid(),
            kind=kind,
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=None if role is None else role.value,
            state="QUEUED",
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def ensure_import_asset_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
    ) -> LibraryImportTaskRecord | None:
        row = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_ASSET",
                LibraryImportTask.resource_id == resource_id,
                LibraryImportTask.source_node_id == source_node_id,
            )
        )
        if row is None:
            return self.enqueue(
                kind="IMPORT_ASSET",
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                role=role,
            )
        if row.state == "SUCCEEDED":
            return None
        if row.state == "FAILED":
            row.state = "QUEUED"
            row.error_summary = None
            row.started_at = None
            row.finished_at = None
            row.role = role.value
            self._session.flush()
        return self._to_record(row)

    def next_queued(self) -> LibraryImportTaskRecord | None:
        row = self._session.scalar(
            select(LibraryImportTask)
            .where(LibraryImportTask.state == "QUEUED")
            .order_by(LibraryImportTask.created_at.asc())
            .limit(1)
        )
        return None if row is None else self._to_record(row)

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        return None if row is None else self._to_record(row)

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        row.state = "RUNNING"
        row.started_at = started_at
        row.error_summary = None
        self._session.flush()

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        row.state = "SUCCEEDED"
        row.finished_at = finished_at
        row.error_summary = None
        self._session.flush()

    def mark_failed(
        self,
        task_id: str,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        row.state = "FAILED"
        row.finished_at = finished_at
        row.error_summary = error_summary
        self._session.flush()

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        result = self._session.execute(
            update(LibraryImportTask)
            .where(LibraryImportTask.state == "RUNNING")
            .values(
                state="FAILED",
                error_summary=WORKER_INTERRUPTED,
                finished_at=finished_at,
            )
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def requeue_failed_for_library(self, library_id: str) -> int:
        result = self._session.execute(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.state == "FAILED",
            )
            .values(
                state="QUEUED",
                error_summary=None,
                started_at=None,
                finished_at=None,
            )
        )
        self._session.flush()
        return int(result.rowcount or 0)

    def requeue_failed_for_source(self, source_node_id: str) -> int:
        result = self._session.execute(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.source_node_id == source_node_id,
                LibraryImportTask.state == "FAILED",
            )
            .values(
                state="QUEUED",
                error_summary=None,
                started_at=None,
                finished_at=None,
            )
        )
        # Also requeue IMPORT_ASSET tasks under resources anchored at this node
        # is handled by CONTINUE_SOURCE scan; FAILED for this source_node covers
        # CONTINUE_SOURCE and file PRIMARY tasks.
        self._session.flush()
        return int(result.rowcount or 0)

    def has_active_kind(
        self,
        *,
        kind: ImportTaskKind,
        library_id: str,
        source_node_id: str | None = None,
    ) -> bool:
        stmt = select(LibraryImportTask.id).where(
            LibraryImportTask.kind == kind,
            LibraryImportTask.library_id == library_id,
            LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
        )
        if source_node_id is not None:
            stmt = stmt.where(LibraryImportTask.source_node_id == source_node_id)
        return self._session.scalar(stmt.limit(1)) is not None

    def _to_record(self, row: LibraryImportTask) -> LibraryImportTaskRecord:
        role: AssetRole | None = None
        if row.role is not None:
            role = AssetRole(row.role)
        return LibraryImportTaskRecord(
            id=row.id,
            kind=cast(ImportTaskKind, row.kind),
            library_id=row.library_id,
            state=cast(ImportTaskState, row.state),
            resource_id=row.resource_id,
            source_node_id=row.source_node_id,
            role=role,
            error_summary=row.error_summary,
        )


__all__ = ["SqlAlchemyReadableResourceWorkQueue"]
