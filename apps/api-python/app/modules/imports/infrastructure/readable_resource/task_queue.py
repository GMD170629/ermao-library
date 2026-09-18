"""Single-consumer LibraryImportTask queue for ADR 0018 ContinueImport."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import and_, delete, exists, literal, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.common import cuid
from app.modules.imports.application.readable_resource.ports import (
    WORKER_INTERRUPTED,
    ImportTaskKind,
    ImportTaskState,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    MissingEntryPolicy,
    PreparedBookIdentification,
)
from app.modules.imports.domain.scan_policy import (
    ScanScope,
    decode_scan_scopes,
    encode_scan_scopes,
    merge_scan_scopes,
    remove_scan_scopes,
)
from app.modules.imports.infrastructure.readable_resource.book_completion import (
    BookImportCompletion,
)
from app.modules.imports.infrastructure.readable_resource.scan_gating import (
    active_imports_for_anchor,
    clear_scan_gaps,
    gap_covers_anchor,
    record_scan_gaps,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportScanGap,
    LibraryImportTask,
)
from app.modules.library.public import AssetRole


class SqlAlchemyLibraryImportTaskQueue(LibraryImportTaskQueuePort):
    def __init__(self, session: Session) -> None:
        self._session = session
        self._completion = BookImportCompletion(session)

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
        for task in self._session.scalars(
            select(LibraryImportTask).where(
                LibraryImportTask.source_node_id.in_(tuple(source_node_ids))
            )
        ):
            self._completion.cancel(task)
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
            resource_anchor_node_id=source_node_id
            if kind == "IMPORT_RESOURCE"
            else None,
            state="QUEUED",
            missing_entry_policy=missing_entry_policy.value,
        )
        self._session.add(row)
        self._session.flush()
        self._completion.dirty(row)
        return self._to_record(row)

    def request_library_scan(
        self,
        library_id: str,
        *,
        missing_entry_policy: MissingEntryPolicy,
        scan_scopes: tuple[ScanScope, ...] | None = None,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        """Merge an equivalent active scan and retain at most one follow-up."""

        queued = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "QUEUED",
            )
        )
        failed = self._session.scalars(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")),
                LibraryImportTask.state == "FAILED",
            )
            .order_by(LibraryImportTask.created_at)
        ).all()
        if failed:
            # A fresh scan request explicitly resumes unfinished scopes. Coalesce
            # their intent before removing superseded failed queue rows.
            for previous in failed:
                if previous.kind == "SCAN_LIBRARY":
                    scopes = decode_scan_scopes(previous.scan_scopes)
                else:
                    node = self._session.get(LibrarySourceNode, previous.source_node_id)
                    scopes = (
                        (
                            ScanScope(
                                node.relative_path
                                if node.physical_kind == "DIRECTORY"
                                else node.relative_path.rpartition("/")[0],
                                True,
                            ),
                        )
                        if node
                        else None
                    )
                scan_scopes = merge_scan_scopes(scan_scopes, scopes)
            survivor = queued if queued is not None else failed[0]
            for offset in range(0, len(failed), 200):
                self._session.execute(
                    delete(LibraryImportTask).where(
                        LibraryImportTask.id.in_(
                            [
                                row.id
                                for row in failed[offset : offset + 200]
                                if row.id != survivor.id
                            ]
                        )
                    )
                )
            if queued is not None:
                scan_scopes = merge_scan_scopes(
                    decode_scan_scopes(queued.scan_scopes), scan_scopes
                )
            survivor.kind = "SCAN_LIBRARY"
            survivor.source_node_id = None
            survivor.scan_scopes = encode_scan_scopes(scan_scopes)
            survivor.state = "QUEUED"
            survivor.finished_at = None
            survivor.started_at = None
            survivor.error_summary = None
            self._promote_missing_entry_policy(survivor, missing_entry_policy)
            self._session.flush()
            return self._to_record(survivor), queued is None
        if queued is not None:
            queued.scan_scopes = encode_scan_scopes(
                merge_scan_scopes(decode_scan_scopes(queued.scan_scopes), scan_scopes)
            )
            self._promote_missing_entry_policy(queued, missing_entry_policy)
            self._session.flush()
            return self._to_record(queued), False

        task_id = cuid()
        statement = (
            sqlite_insert(LibraryImportTask)
            .values(
                id=task_id,
                kind="SCAN_LIBRARY",
                library_id=library_id,
                state="QUEUED",
                missing_entry_policy=missing_entry_policy.value,
                scan_scopes=encode_scan_scopes(scan_scopes),
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
        if not inserted:
            row.scan_scopes = encode_scan_scopes(
                merge_scan_scopes(decode_scan_scopes(row.scan_scopes), scan_scopes)
            )
            self._session.flush()
        if inserted:
            self._completion.dirty(row)
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

        failed_source = self._session.scalar(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.kind == "CONTINUE_SOURCE",
                LibraryImportTask.library_id == library_id,
                LibraryImportTask.source_node_id == source_node_id,
                LibraryImportTask.state == "FAILED",
            )
            .order_by(LibraryImportTask.created_at)
            .limit(1)
        )
        if failed_source is not None:
            self._promote_missing_entry_policy(failed_source, missing_entry_policy)
            return self.requeue_failed_task(failed_source.id)

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

    def request_import_resource(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        changed: bool = False,
        force: bool = False,
    ) -> LibraryImportTaskRecord | None:
        resource = self._session.get(LibraryReadableResource, resource_id)
        if (
            resource is None
            or resource.library_id != library_id
            or resource.source_node_id != source_node_id
        ):
            raise ValueError("INVALID_RESOURCE_TASK_TARGET")
        if force:
            # Keep IDs, READY results and navigation readable until replacement.
            # Clearing only the successful version forces extraction on the next run.
            self._session.execute(
                update(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.library_id == library_id,
                )
                .values(processed_source_version=None)
            )
            changed = True
        row = self._session.scalar(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.kind == "IMPORT_RESOURCE",
                LibraryImportTask.resource_id == resource_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            return self.enqueue(
                kind="IMPORT_RESOURCE",
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
            )
        if row.state == "RUNNING":
            if changed and not row.rerun_requested:
                row.rerun_requested = True
                self._completion.dirty(row)
        elif row.state == "FAILED" or (row.state == "SUCCEEDED" and changed):
            row.state = "QUEUED"
            row.error_summary = None
            row.started_at = None
            row.finished_at = None
            self._completion.dirty(row)
        elif row.state == "SUCCEEDED":
            return None
        self._session.flush()
        return self._to_record(row)

    def next_queued(self) -> LibraryImportTaskRecord | None:
        """Select the oldest queued task whose necessary inputs are ready.

        Dependencies are path and scope based, not library based. A queued
        IMPORT_RESOURCE for a single file is always executable because its node
        and observation are already committed. A directory resource waits while
        a durable incomplete range covers its anchor, so deleting or replacing a
        failed scan task never releases it. An IDENTIFY_BOOK waits for such a
        range on its own path or for active import work below it; an unrelated
        scoped scan does not block it.
        """
        anchor = aliased(LibrarySourceNode)
        blocked_by_gap = gap_covers_anchor(
            LibraryImportTask.library_id, anchor
        ).correlate(LibraryImportTask).correlate(anchor)
        is_directory_resource = exists(
            select(literal(1))
            .select_from(LibraryReadableResource)
            .where(
                LibraryReadableResource.id == LibraryImportTask.resource_id,
                LibraryReadableResource.format.in_(("IMAGE_DIR", "AUDIOBOOK_DIR")),
            )
        )
        identify_anchor = aliased(LibrarySourceNode)
        identify_blocked = or_(
            active_imports_for_anchor(
                identify_anchor,
                library_id=LibraryImportTask.library_id,
                anchor_id=LibraryImportTask.source_node_id,
            ),
            blocked_by_gap,
        )
        executable = or_(
            LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")),
            and_(
                LibraryImportTask.kind == "IMPORT_RESOURCE",
                or_(~is_directory_resource, ~blocked_by_gap),
            ),
            and_(LibraryImportTask.kind == "IDENTIFY_BOOK", ~identify_blocked),
        )
        row = self._session.scalar(
            select(LibraryImportTask)
            .outerjoin(anchor, anchor.id == LibraryImportTask.source_node_id)
            .where(
                LibraryImportTask.state == "QUEUED",
                executable,
            )
            .order_by(
                LibraryImportTask.created_at.asc(),
                LibraryImportTask.id.asc(),
            )
            .limit(1)
        )
        return None if row is None else self._to_record(row)

    def prepare_book_identifications(self) -> tuple[PreparedBookIdentification, ...]:
        return self._completion.prepare_ready()

    def enqueue_book_identifications(
        self, prepared: tuple[PreparedBookIdentification, ...]
    ) -> int:
        return self._completion.persist_ready(prepared)

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        return None if row is None else self._to_record(row)

    def mark_running(self, task_id: str, *, started_at: datetime) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        row.state = "RUNNING"
        if row.kind == "IMPORT_RESOURCE":
            row.rerun_requested = False
        if row.kind == "IDENTIFY_BOOK":
            row.book_metadata_revision = self._session.scalar(
                select(LibraryBookMetadata.import_revision)
                .join(LibraryBook)
                .where(LibraryBook.source_node_id == row.source_node_id)
            )
        row.started_at = started_at
        row.error_summary = None
        self._session.flush()

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        if row.kind == "IMPORT_RESOURCE" and row.rerun_requested:
            row.state = "QUEUED"
            row.rerun_requested = False
            row.started_at = None
            row.finished_at = None
            row.error_summary = None
            self._session.flush()
            return
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
        if row.kind == "IMPORT_RESOURCE" and row.rerun_requested:
            row.state = "QUEUED"
            row.rerun_requested = False
            row.started_at = None
            row.finished_at = None
            row.error_summary = None
            self._session.flush()
            return
        row.state = "FAILED"
        row.finished_at = finished_at
        row.error_summary = error_summary
        self._session.flush()
        self._completion.finished(row)

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        # An interrupted process left partial enumeration behind. Preserve its
        # unfinished ranges durably before the task rows become historical.
        running = self._session.scalars(
            select(LibraryImportTask).where(
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")),
            )
        ).all()
        for task in running:
            self._record_gaps_for_task(task)
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

    def has_incomplete_ranges(self, library_id: str) -> bool:
        row = self._session.get(LibraryImportScanGap, library_id)
        return row is not None and bool(row.scopes)

    def apply_scan_round(
        self,
        task_id: str | None,
        library_id: str,
        *,
        resolved: tuple[ScanScope, ...],
        incomplete: tuple[ScanScope, ...],
    ) -> None:
        resolved_scopes = merge_scan_scopes((), resolved) or ()
        incomplete_scopes = merge_scan_scopes((), incomplete) or ()
        if task_id is not None:
            row = self._session.get(LibraryImportTask, task_id)
            if row is not None and row.kind == "SCAN_LIBRARY":
                remaining = remove_scan_scopes(
                    decode_scan_scopes(row.scan_scopes) or (), resolved_scopes
                )
                combined = merge_scan_scopes(remaining, incomplete_scopes) or ()
                row.scan_scopes = (
                    encode_scan_scopes(combined) if combined else None
                )
        if resolved_scopes:
            clear_scan_gaps(self._session, library_id, resolved_scopes)
        if incomplete_scopes:
            record_scan_gaps(self._session, library_id, incomplete_scopes)

    def _record_gaps_for_task(self, task: LibraryImportTask) -> None:
        if task.kind == "SCAN_LIBRARY":
            scopes = decode_scan_scopes(task.scan_scopes)
            if scopes is None:
                scopes = (ScanScope("", True),)
        elif task.source_node_id is not None:
            node = self._session.get(LibrarySourceNode, task.source_node_id)
            scopes = (
                (ScanScope(node.relative_path, True),) if node is not None else ()
            )
        else:
            return
        record_scan_gaps(self._session, task.library_id, scopes)

    def requeue_failed_task(self, task_id: str) -> tuple[LibraryImportTaskRecord, bool]:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None:
            raise LookupError(task_id)
        if row.state != "FAILED":
            return self._to_record(row), False
        if row.kind == "IDENTIFY_BOOK":
            active = self._session.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IDENTIFY_BOOK",
                    LibraryImportTask.source_node_id == row.source_node_id,
                    LibraryImportTask.state.in_(("QUEUED", "RUNNING")),
                )
            )
            if active is not None:
                return self._to_record(active), False
        row.state = "QUEUED"
        row.error_summary = None
        row.started_at = None
        row.finished_at = None
        self._completion.dirty(row)
        if row.kind == "IDENTIFY_BOOK":
            self._session.execute(
                update(LibraryBookMetadata)
                .where(
                    LibraryBookMetadata.book_id.in_(
                        select(LibraryBook.id).where(
                            LibraryBook.source_node_id == row.source_node_id
                        )
                    )
                )
                .values(metadata_pending=True, metadata_state="QUEUED")
            )
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
            scan_scopes=decode_scan_scopes(row.scan_scopes),
        )


__all__ = ["SqlAlchemyLibraryImportTaskQueue"]
