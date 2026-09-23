"""Single-consumer LibraryImportTask queue for ADR 0018 ContinueImport."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, aliased

from app.contracts.library_file_activity import LibraryFileActivityBusy
from app.contracts.source_relocation import SourceRelocation
from app.core.exception_diagnostics import prepare_exception_diagnostic
from app.infrastructure.file_operation_conflicts import file_operation_blocks_library
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.models.common import cuid
from app.modules.imports.application.readable_resource.book_work import (
    BookWork,
    BookWorkState,
    decode_book_work,
    encode_book_work,
)
from app.modules.imports.application.readable_resource.ports import (
    WORKER_INTERRUPTED,
    BookImportTaskQueuePort,
    BookImportTaskRecord,
    ImportTaskKind,
    ImportTaskState,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    MissingEntryPolicy,
)
from app.modules.imports.domain.scan_policy import (
    ScanScope,
    decode_scan_scopes,
    encode_scan_scopes,
    merge_scan_scopes,
    path_contains,
    remove_scan_scopes,
)
from app.modules.imports.infrastructure.readable_resource.book_completion import (
    BookImportCompletion,
)
from app.modules.imports.infrastructure.readable_resource.scan_gating import (
    clear_scan_gaps,
    gap_covers_anchor,
    record_scan_gaps,
)
from app.modules.imports.infrastructure.readable_resource_import_schema import (
    LibraryImportScanGap,
    LibraryImportTask,
)
from app.modules.library.public import AssetRole


class ImportTaskInterrupted(RuntimeError):
    """Startup observed a task still running from the previous worker lifetime."""


class SqlAlchemyLibraryImportTaskQueue(
    LibraryImportTaskQueuePort, BookImportTaskQueuePort
):
    _MAX_BOOK_RETRIES = 3

    def __init__(self, session: Session) -> None:
        self._session = session
        self._completion = BookImportCompletion(session)

    @staticmethod
    def _book_phase(work: BookWork) -> str:
        if work.scan_scopes != ():
            return "SCAN"
        if work.resource_ids != ():
            return "RESOURCES"
        return "IDENTIFY"

    @staticmethod
    def _book_record(row: LibraryImportTask) -> BookImportTaskRecord:
        if (
            row.book_id is None
            or row.source_node_id is None
            or row.phase is None
            or row.book_work is None
        ):
            raise ValueError("INVALID_BOOK_TASK")
        return BookImportTaskRecord(
            id=row.id,
            book_id=row.book_id,
            library_id=row.library_id,
            source_node_id=row.source_node_id,
            state=cast("ImportTaskState", row.state),
            phase=row.phase,
            request_version=row.request_version,
            execution_version=row.execution_version,
            work=decode_book_work(row.book_work),
            resource_cursor=row.resource_cursor,
            retry_count=row.retry_count,
            next_attempt_at=row.next_attempt_at,
            error_summary=row.error_summary,
        )

    def request_book_work(
        self, *, book_id: str, work: BookWork, requested_at: datetime
    ) -> BookImportTaskRecord:
        if work.is_empty:
            raise ValueError("EMPTY_BOOK_WORK")
        book = self._session.get(LibraryBook, book_id)
        if book is None:
            raise LookupError(book_id)
        anchor = self._session.get(LibrarySourceNode, book.source_node_id)
        if anchor is None or anchor.library_id != book.library_id:
            raise ValueError("INVALID_BOOK_ANCHOR")
        if work.scan_scopes is not None and any(
            not path_contains(anchor.relative_path, scope.relative_path)
            or (
                anchor.physical_kind == "REGULAR_FILE"
                and scope.relative_path != anchor.relative_path
            )
            for scope in work.scan_scopes
        ):
            raise ValueError("SCAN_SCOPE_OUTSIDE_BOOK")
        if work.resource_ids not in (None, ()):
            owned = set(
                self._session.scalars(
                    select(LibraryReadableResource.id).where(
                        LibraryReadableResource.id.in_(work.resource_ids),
                        LibraryReadableResource.book_id == book_id,
                        LibraryReadableResource.library_id == book.library_id,
                    )
                ).all()
            )
            if owned != set(work.resource_ids):
                raise ValueError("RESOURCE_OUTSIDE_BOOK")

        row = self._session.scalar(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.book_id == book_id,
            )
        )
        if row is None:
            task_id = cuid()
            self._session.execute(
                sqlite_insert(LibraryImportTask)
                .values(
                    id=task_id,
                    kind="IMPORT_BOOK",
                    book_id=book_id,
                    library_id=book.library_id,
                    source_node_id=book.source_node_id,
                    state="QUEUED",
                    phase=self._book_phase(work),
                    book_work=encode_book_work(BookWorkState(pending=work)),
                    request_version=1,
                    retry_count=0,
                    next_attempt_at=requested_at,
                    created_at=requested_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[LibraryImportTask.book_id],
                    index_where=LibraryImportTask.kind == "IMPORT_BOOK",
                )
            )
            row = self._session.scalar(
                select(LibraryImportTask).where(
                    LibraryImportTask.kind == "IMPORT_BOOK",
                    LibraryImportTask.book_id == book_id,
                )
            )
            if row is None:
                raise RuntimeError("BOOK_TASK_DISAPPEARED")
            if row.id == task_id:
                self._completion.dirty(row)
                return self._book_record(row)

        if row.source_node_id != book.source_node_id or row.library_id != book.library_id:
            raise ValueError("BOOK_TASK_ANCHOR_MISMATCH")
        current = decode_book_work(row.book_work or "")
        merged = current.request(work)
        values: dict[str, object] = {
            "book_work": encode_book_work(merged),
            "request_version": row.request_version + 1,
        }
        if row.state in {"SUCCEEDED", "FAILED"}:
            values.update(
                state="QUEUED",
                phase=self._book_phase(
                    merged.active if not merged.active.is_empty else merged.pending
                ),
                started_at=None,
                finished_at=None,
                error_summary=None,
                retry_count=0,
                next_attempt_at=requested_at,
            )
        changed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == row.id,
                LibraryImportTask.request_version == row.request_version,
            )
            .values(**values)
            .returning(LibraryImportTask.id)
        )
        if changed is None:
            raise RuntimeError("BOOK_REQUEST_VERSION_CONFLICT")
        self._session.refresh(row)
        self._completion.dirty(row)
        return self._book_record(row)

    def claim_next_book(self, *, started_at: datetime) -> BookImportTaskRecord | None:
        anchor = aliased(LibrarySourceNode)
        row = self._session.scalar(
            select(LibraryImportTask)
            .join(anchor, anchor.id == LibraryImportTask.source_node_id)
            .where(
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "QUEUED",
                LibraryImportTask.next_attempt_at <= started_at,
                ~file_operation_blocks_library(LibraryImportTask.library_id),
                or_(
                    anchor.physical_kind == "REGULAR_FILE",
                    LibraryImportTask.phase == "SCAN",
                    ~gap_covers_anchor(LibraryImportTask.library_id, anchor),
                ),
            )
            .order_by(
                LibraryImportTask.next_attempt_at.asc(),
                LibraryImportTask.created_at.asc(),
                LibraryImportTask.id.asc(),
            )
            .limit(1)
        )
        if row is None:
            return None
        work = decode_book_work(row.book_work or "")
        if work.active.is_empty:
            work = work.claim_new()
            execution_version = row.request_version
            phase = self._book_phase(work.active)
        else:
            if row.execution_version is None:
                raise ValueError("BOOK_RUN_VERSION_MISSING")
            execution_version = row.execution_version
            phase = row.phase
        claimed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == row.id,
                LibraryImportTask.state == "QUEUED",
                LibraryImportTask.request_version == row.request_version,
            )
            .values(
                state="RUNNING",
                phase=phase,
                book_work=encode_book_work(work),
                execution_version=execution_version,
                started_at=started_at,
                finished_at=None,
                error_summary=None,
            )
            .returning(LibraryImportTask.id)
        )
        if claimed is None:
            return None
        self._session.refresh(row)
        return self._book_record(row)

    def get_book_task(self, task_id: str) -> BookImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id, populate_existing=True)
        return self._book_record(row) if row is not None and row.kind == "IMPORT_BOOK" else None

    def book_identification_complete(self, book_id: str) -> bool:
        return self._session.scalar(
            select(LibraryBookMetadata.book_id).where(
                LibraryBookMetadata.book_id == book_id,
                LibraryBookMetadata.metadata_pending.is_(False),
                LibraryBookMetadata.processed_revision
                == LibraryBookMetadata.import_revision,
            )
        ) is not None

    def book_run_is_current(
        self,
        task_id: str,
        *,
        execution_version: int,
        require_latest_request: bool = False,
    ) -> bool:
        conditions = [
            LibraryImportTask.id == task_id,
            LibraryImportTask.kind == "IMPORT_BOOK",
            LibraryImportTask.state == "RUNNING",
            LibraryImportTask.execution_version == execution_version,
        ]
        if require_latest_request:
            conditions.append(LibraryImportTask.request_version == execution_version)
        return self._session.scalar(
            select(LibraryImportTask.id).where(*conditions)
        ) is not None

    def advance_book_resource_cursor(
        self, task_id: str, *, execution_version: int, resource_id: str
    ) -> bool:
        row = self._session.get(LibraryImportTask, task_id, populate_existing=True)
        if (
            row is None
            or row.kind != "IMPORT_BOOK"
            or row.state != "RUNNING"
            or row.execution_version != execution_version
        ):
            return False
        work = decode_book_work(row.book_work or "").active
        if work.resource_ids is None:
            next_resource_id = self._session.scalar(
                select(LibraryReadableResource.id)
                .where(
                    LibraryReadableResource.book_id == row.book_id,
                    LibraryReadableResource.library_id == row.library_id,
                    LibraryReadableResource.id > (row.resource_cursor or ""),
                )
                .order_by(LibraryReadableResource.id)
                .limit(1)
            )
        else:
            next_resource_id = next(
                (
                    candidate
                    for candidate in sorted(work.resource_ids)
                    if row.resource_cursor is None or candidate > row.resource_cursor
                ),
                None,
            )
        if next_resource_id != resource_id:
            raise ValueError("BOOK_RESOURCE_CURSOR_OUT_OF_ORDER")
        advanced = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.resource_cursor == row.resource_cursor,
            )
            .values(resource_cursor=resource_id)
            .returning(LibraryImportTask.id)
        )
        return advanced is not None

    def advance_book_phase(
        self, task_id: str, *, execution_version: int, phase: str
    ) -> bool:
        if phase not in {"RESOURCES", "IDENTIFY"}:
            raise ValueError("INVALID_BOOK_PHASE")
        advanced = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.phase.in_(
                    ("SCAN", "RESOURCES")
                    if phase == "RESOURCES"
                    else ("SCAN", "RESOURCES", "IDENTIFY")
                ),
            )
            .values(phase=phase)
            .returning(LibraryImportTask.id)
        )
        return advanced is not None

    def yield_book_run(
        self, task_id: str, *, execution_version: int, yielded_at: datetime
    ) -> BookImportTaskRecord | None:
        yielded = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.phase == "RESOURCES",
            )
            .values(state="QUEUED", next_attempt_at=yielded_at, started_at=None)
            .returning(LibraryImportTask.id)
        )
        return self.get_book_task(yielded) if yielded is not None else None

    def finish_book_run(
        self, task_id: str, *, execution_version: int, finished_at: datetime
    ) -> BookImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        if (
            row is None
            or row.kind != "IMPORT_BOOK"
            or row.state != "RUNNING"
            or row.execution_version != execution_version
        ):
            return None
        work = decode_book_work(row.book_work or "")
        if work.active.is_empty:
            raise ValueError("BOOK_WORK_NOT_ACTIVE")
        remaining = work.finish_active()
        if work.active.identify and not remaining.pending.is_empty:
            remaining = BookWorkState(
                pending=remaining.pending.merge(BookWork(identify=True))
            )
        has_follow_up = not remaining.pending.is_empty
        if not has_follow_up and row.request_version != execution_version:
            raise ValueError("BOOK_REQUEST_VERSION_WITHOUT_WORK")
        if not has_follow_up and self._session.scalar(
            select(LibraryBookMetadata.metadata_pending).where(
                LibraryBookMetadata.book_id == row.book_id
            )
        ):
            raise ValueError("BOOK_IDENTIFICATION_PENDING")
        values: dict[str, object] = {
            "book_work": encode_book_work(remaining),
            "execution_version": None,
            "resource_cursor": None,
            "retry_count": 0,
            "state": "QUEUED" if has_follow_up else "SUCCEEDED",
            "phase": self._book_phase(remaining.pending)
            if has_follow_up
            else "FINALIZE",
            "finished_at": None if has_follow_up else finished_at,
            "next_attempt_at": finished_at if has_follow_up else row.next_attempt_at,
            "error_summary": None,
        }
        finished = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.request_version == row.request_version,
            )
            .values(**values)
            .returning(LibraryImportTask.id)
        )
        if finished is None:
            return None
        self._session.refresh(row)
        return self._book_record(row)

    def fail_book_run(
        self,
        task_id: str,
        *,
        execution_version: int,
        error_summary: str,
        retryable: bool,
        failed_at: datetime,
        partial_failure: bool = False,
    ) -> BookImportTaskRecord | None:
        if not error_summary:
            raise ValueError("EMPTY_BOOK_FAILURE")
        row = self._session.get(LibraryImportTask, task_id)
        if (
            row is None
            or row.kind != "IMPORT_BOOK"
            or row.state != "RUNNING"
            or row.execution_version != execution_version
        ):
            return None
        attempts = row.retry_count + 1
        will_retry = retryable and attempts <= self._MAX_BOOK_RETRIES
        work = decode_book_work(row.book_work or "")
        has_new_request = not work.pending.is_empty
        roll_forward = has_new_request and not will_retry
        if partial_failure and row.phase != "IDENTIFY":
            raise ValueError("BOOK_PARTIAL_FAILURE_PHASE_MISMATCH")
        next_work = (
            BookWorkState(pending=work.active.merge(work.pending))
            if roll_forward
            else work
        )
        terminal_failure = not will_retry and not roll_forward
        failed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.request_version == row.request_version,
            )
            .values(
                state="FAILED" if terminal_failure else "QUEUED",
                book_work=encode_book_work(next_work),
                phase=(
                    self._book_phase(next_work.pending)
                    if roll_forward
                    else "RESOURCES" if partial_failure else row.phase
                ),
                execution_version=None if roll_forward else row.execution_version,
                resource_cursor=None
                if roll_forward or partial_failure
                else row.resource_cursor,
                retry_count=0 if roll_forward else attempts,
                next_attempt_at=(
                    failed_at
                    if roll_forward
                    else failed_at + timedelta(seconds=30 * (4 ** (attempts - 1)))
                    if will_retry
                    else None
                ),
                finished_at=failed_at if terminal_failure else None,
                error_summary=error_summary,
            )
            .returning(LibraryImportTask.id)
        )
        if failed is None:
            return None
        if terminal_failure and not partial_failure:
            self._session.execute(
                update(LibraryBookMetadata)
                .where(LibraryBookMetadata.book_id == row.book_id)
                .values(metadata_pending=False, metadata_state="FAILED")
            )
        self._session.refresh(row)
        return self._book_record(row)

    def continue_book_task(
        self, task_id: str, *, continued_at: datetime, force: bool = False
    ) -> tuple[BookImportTaskRecord, bool] | None:
        requested = self._session.get(LibraryImportTask, task_id)
        if requested is None:
            raise LookupError(task_id)
        current_id = (
            requested.id
            if requested.kind == "IMPORT_BOOK"
            else requested.superseded_by_task_id
        )
        if current_id is None:
            return None
        current = self._session.get(LibraryImportTask, current_id)
        if (
            current is None
            or current.kind != "IMPORT_BOOK"
            or current.book_id is None
            or current.library_id != requested.library_id
        ):
            raise LookupError(task_id)
        if force:
            if requested.kind != "IMPORT_RESOURCE" or requested.resource_id is None:
                raise ValueError("FORCE_REQUIRES_RESOURCE_TASK")
            resource = self._session.get(
                LibraryReadableResource, requested.resource_id
            )
            if (
                resource is None
                or resource.book_id != current.book_id
                or resource.library_id != current.library_id
            ):
                raise ValueError("RESOURCE_OUTSIDE_BOOK")
            self._session.execute(
                update(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resource.id,
                    LibraryResourceAsset.library_id == current.library_id,
                )
                .values(processed_source_version=None)
            )
            book_task = self.request_book_work(
                book_id=current.book_id,
                work=BookWork(resource_ids=(resource.id,)),
                requested_at=continued_at,
            )
            return book_task, True
        if current.state != "FAILED":
            return self._book_record(current), False
        work = decode_book_work(current.book_work or "")
        if work.active.is_empty and work.pending.is_empty:
            raise ValueError("BOOK_WORK_NOT_PENDING")
        changed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == current.id,
                LibraryImportTask.state == "FAILED",
                LibraryImportTask.request_version == current.request_version,
            )
            .values(
                state="QUEUED",
                phase=self._book_phase(
                    work.active if not work.active.is_empty else work.pending
                ),
                next_attempt_at=continued_at,
                retry_count=0,
                started_at=None,
                finished_at=None,
                error_summary=None,
            )
            .returning(LibraryImportTask.id)
        )
        if changed is None:
            raise RuntimeError("BOOK_CONTINUE_VERSION_CONFLICT")
        self._session.refresh(current)
        self._completion.dirty(current)
        return self._book_record(current), True

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
        if not changed and resource.import_state == "READY":
            any_asset = exists(
                select(LibraryResourceAsset.id).where(
                    LibraryResourceAsset.resource_id == resource_id
                )
            )
            incomplete_asset = exists(
                select(LibraryResourceAsset.id).where(
                    LibraryResourceAsset.resource_id == resource_id,
                    or_(
                        LibraryResourceAsset.import_state != "READY",
                        LibraryResourceAsset.processed_source_version.is_(None),
                    ),
                )
            )
            has_asset, has_incomplete = self._session.execute(
                select(any_asset, incomplete_asset)
            ).one()
            if has_asset and not has_incomplete:
                return None
        book_task = self.request_book_work(
            book_id=resource.book_id,
            work=BookWork(resource_ids=(resource_id,)),
            requested_at=datetime.now(UTC),
        )
        row = self._session.get(LibraryImportTask, book_task.id)
        if row is None:
            raise RuntimeError("BOOK_TASK_DISAPPEARED")
        return self._to_record(row)

    def next_queued(self) -> LibraryImportTaskRecord | None:
        """Select discovery work; Book work has its own indexed claim path."""
        row = self._session.scalar(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE")),
                LibraryImportTask.state == "QUEUED",
                LibraryImportTask.superseded_by_task_id.is_(None),
                ~file_operation_blocks_library(LibraryImportTask.library_id),
            )
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
        claimed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.state == "QUEUED",
                LibraryImportTask.superseded_by_task_id.is_(None),
                ~file_operation_blocks_library(LibraryImportTask.library_id),
            )
            .values(state="RUNNING")
            .returning(LibraryImportTask.id)
        )
        if claimed is None:
            current = self._session.get(
                LibraryImportTask, task_id, populate_existing=True
            )
            if current is None:
                raise LookupError(task_id)
            if current.state != "QUEUED":
                raise ValueError("IMPORT_TASK_NOT_QUEUED")
            raise LibraryFileActivityBusy("LIBRARY_FILE_ACTIVITY_BUSY")
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
            )
        ).all()
        for task in running:
            prepare_exception_diagnostic(
                logging.getLogger(__name__), "import.task_interrupted",
                ImportTaskInterrupted(
                    "Startup observed a persisted RUNNING task without a terminal result from the previous worker lifetime; interruption cause was not provided"
                ),
                context={
                    "task_id": task.id, "task_kind": task.kind,
                    "library_id": task.library_id, "resource_id": task.resource_id,
                    "source_node_id": task.source_node_id, "step": "startup_recovery",
                    "outcome": "QUEUED" if task.kind == "IMPORT_BOOK" else "FAILED",
                    "code": WORKER_INTERRUPTED,
                },
            )
            if task.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
                self._record_gaps_for_task(task)
        result = self._session.execute(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.kind != "IMPORT_BOOK",
            )
            .values(
                state="FAILED",
                error_summary=WORKER_INTERRUPTED,
                finished_at=finished_at,
            )
        )
        resumed = self._session.execute(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.kind == "IMPORT_BOOK",
            )
            .values(
                state="QUEUED",
                error_summary=WORKER_INTERRUPTED,
                started_at=None,
                finished_at=None,
                next_attempt_at=finished_at,
            )
        )
        self._session.flush()
        return int(getattr(result, "rowcount", 0) or 0) + int(
            getattr(resumed, "rowcount", 0) or 0
        )

    def reconcile_relocation(self, change: SourceRelocation) -> None:
        """Relocate scoped checkpoints and reconcile only the moved publication."""
        source_scope = ScanScope(change.source_relative_path, True)
        destination_scope = ScanScope(change.destination_relative_path, True)
        # Composite node/resource foreign keys already move node-bound task scope.
        # Keep unrelated and broad source gaps; only the removed subtree is cleared.
        clear_scan_gaps(self._session, change.source_library_id, (source_scope,))
        if change.reimport:
            self.request_library_scan(
                change.source_library_id,
                missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                scan_scopes=(
                    ScanScope(change.source_relative_path.rpartition("/")[0], False),
                ),
            )
        record_scan_gaps(
            self._session, change.destination_library_id, (destination_scope,)
        )
        self.request_library_scan(
            change.destination_library_id,
            missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
            scan_scopes=(destination_scope,),
        )

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
                row.scan_scopes = encode_scan_scopes(combined) if combined else None
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
            scopes = (ScanScope(node.relative_path, True),) if node is not None else ()
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
