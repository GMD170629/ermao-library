"""Single-consumer LibraryImportTask queue for ADR 0018 ContinueImport."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.common import cuid
from app.modules.imports.application.readable_resource.ports import (
    WORKER_INTERRUPTED,
    ImportTaskKind,
    ImportTaskState,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    MissingEntryPolicy,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportTask,
)
from app.modules.library.public import AssetRole


class SqlAlchemyLibraryImportTaskQueue(LibraryImportTaskQueuePort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_with_fresh_library_scan(self, library_id: str) -> None:
        """Drop every target task for the library and enqueue one SCAN_LIBRARY."""
        self._session.execute(
            delete(LibraryImportTask).where(LibraryImportTask.library_id == library_id)
        )
        self._session.flush()
        self.enqueue(
            kind="SCAN_LIBRARY",
            library_id=library_id,
            missing_entry_policy=MissingEntryPolicy.PRESERVE,
        )

    def delete_tasks_for_source_nodes(self, source_node_ids: Sequence[str]) -> None:
        if not source_node_ids:
            return
        self._session.execute(
            delete(LibraryImportTask).where(
                LibraryImportTask.source_node_id.in_(tuple(source_node_ids))
            )
        )
        self._session.flush()

    def enqueue(
        self,
        *,
        kind: ImportTaskKind,
        library_id: str,
        resource_id: str | None = None,
        source_node_id: str | None = None,
        role: AssetRole | None = None,
        missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE,
    ) -> LibraryImportTaskRecord:
        row = LibraryImportTask(
            id=cuid(),
            kind=kind,
            library_id=library_id,
            resource_id=resource_id,
            source_node_id=source_node_id,
            role=None if role is None else role.value,
            state="QUEUED",
            missing_entry_policy=missing_entry_policy.value,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def request_library_scan(
        self,
        library_id: str,
        *,
        missing_entry_policy: MissingEntryPolicy,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        """Merge an equivalent active scan and retain at most one follow-up."""

        queued = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "QUEUED",
            )
        )
        if queued is not None:
            self._promote_missing_entry_policy(queued, missing_entry_policy)
            return self._to_record(queued), False

        running = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "RUNNING",
            )
        )
        needs_follow_up = (
            running is not None
            and missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
            and running.missing_entry_policy != MissingEntryPolicy.PRUNE_MISSING.value
        )
        if running is not None and not needs_follow_up:
            return self._to_record(running), False

        task_id = cuid()
        statement = (
            sqlite_insert(LibraryImportTask)
            .values(
                id=task_id,
                kind="SCAN_LIBRARY",
                library_id=library_id,
                state="QUEUED",
                missing_entry_policy=missing_entry_policy.value,
            )
            .on_conflict_do_nothing(
                index_elements=[LibraryImportTask.library_id],
                index_where=(
                    (LibraryImportTask.kind == "SCAN_LIBRARY")
                    & (LibraryImportTask.state == "QUEUED")
                ),
            )
        )
        result = self._session.execute(statement)
        self._session.flush()
        inserted = bool(getattr(result, "rowcount", 0))
        row = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "QUEUED",
            )
        )
        if row is None:
            raise RuntimeError("queued library scan disappeared after request")
        self._promote_missing_entry_policy(row, missing_entry_policy)
        return self._to_record(row), inserted

    def request_source_scan(
        self,
        *,
        library_id: str,
        source_node_id: str,
        missing_entry_policy: MissingEntryPolicy,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        queued = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "CONTINUE_SOURCE",
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.source_node_id == source_node_id,
                LibraryImportTask.state == "QUEUED",
            )
        )
        if queued is not None:
            self._promote_missing_entry_policy(queued, missing_entry_policy)
            return self._to_record(queued), False

        running = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "CONTINUE_SOURCE",
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.source_node_id == source_node_id,
                LibraryImportTask.state == "RUNNING",
            )
        )
        needs_follow_up = (
            running is not None
            and missing_entry_policy is MissingEntryPolicy.PRUNE_MISSING
            and running.missing_entry_policy != MissingEntryPolicy.PRUNE_MISSING.value
        )
        if running is not None and not needs_follow_up:
            return self._to_record(running), False

        task = self.enqueue(
            kind="CONTINUE_SOURCE",
            library_id=library_id,
            source_node_id=source_node_id,
            missing_entry_policy=missing_entry_policy,
        )
        return task, True

    def _promote_missing_entry_policy(
        self,
        task: LibraryImportTask,
        requested: MissingEntryPolicy,
    ) -> None:
        if (
            requested is MissingEntryPolicy.PRUNE_MISSING
            and task.missing_entry_policy != MissingEntryPolicy.PRUNE_MISSING.value
        ):
            task.missing_entry_policy = MissingEntryPolicy.PRUNE_MISSING.value
            self._session.flush()

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

    def requeue_import_asset_task(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
    ) -> LibraryImportTaskRecord:
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
            .order_by(
                LibraryImportTask.created_at.asc(),
                LibraryImportTask.id.asc(),
            )
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
        return int(getattr(result, "rowcount", 0) or 0)

    def requeue_failed_task(self, task_id: str) -> tuple[LibraryImportTaskRecord, bool]:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        if row.state != "FAILED":
            return self._to_record(row), False
        row.state = "QUEUED"
        row.error_summary = None
        row.started_at = None
        row.finished_at = None
        self._session.flush()
        return self._to_record(row), True

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
            missing_entry_policy=MissingEntryPolicy(row.missing_entry_policy),
        )


__all__ = ["SqlAlchemyLibraryImportTaskQueue"]
