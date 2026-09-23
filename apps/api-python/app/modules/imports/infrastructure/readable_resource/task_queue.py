"""Single-consumer LibraryImportTask queue for ADR 0018 ContinueImport."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.orm import Session

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
    book_gate_blocked,
    clear_scan_gaps,
    record_scan_gaps,
    refresh_book_gates,
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
            directory_resource_id=row.directory_resource_id,
            directory_member_cursor=row.directory_member_cursor,
            directory_cover_cursor=row.directory_cover_cursor,
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

        row = LibraryImportTask(
            id=cuid(),
            kind="IMPORT_BOOK",
            book_id=book_id,
            library_id=book.library_id,
            source_node_id=book.source_node_id,
            state="QUEUED",
            phase=self._book_phase(work),
            book_work=encode_book_work(BookWorkState(pending=work)),
            scan_gate_blocked=False,
            request_version=1,
            retry_count=0,
            created_at=requested_at,
        )
        self._session.add(row)
        self._session.flush()
        return self._book_record(row)

    def claim_next_book(self, *, started_at: datetime) -> BookImportTaskRecord | None:
        task_id = self._session.scalar(
            select(LibraryImportTask.id)
            .where(LibraryImportTask.kind == "IMPORT_BOOK", LibraryImportTask.state == "QUEUED")
            .order_by(LibraryImportTask.created_at, LibraryImportTask.id)
            .limit(1)
        )
        return self.claim_book_task(task_id, started_at=started_at) if task_id else None

    def claim_book_task(
        self, task_id: str, *, started_at: datetime
    ) -> BookImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None or row.kind != "IMPORT_BOOK" or row.state != "QUEUED":
            return None
        work = decode_book_work(row.book_work or "")
        if not work.active.is_empty:
            raise ValueError("BOOK_TASK_ALREADY_ATTEMPTED")
        work = work.claim_new()
        claimed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == row.id,
                LibraryImportTask.state == "QUEUED",
                ~file_operation_blocks_library(LibraryImportTask.library_id),
            )
            .values(
                state="RUNNING",
                phase=self._book_phase(work.active),
                book_work=encode_book_work(work),
                execution_version=row.request_version,
                started_at=started_at,
            )
            .returning(LibraryImportTask.id)
        )
        if claimed is None:
            return None
        self._completion.dirty(row)
        self._session.refresh(row)
        return self._book_record(row)

    def refresh_scan_gate_page(self) -> int:
        """Recover unknown gate projections before ordinary Book claiming."""
        return refresh_book_gates(self._session)

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
            .values(
                resource_cursor=resource_id,
                directory_resource_id=None,
                directory_member_cursor=None,
                directory_cover_cursor=None,
            )
            .returning(LibraryImportTask.id)
        )
        return advanced is not None

    def advance_directory_member_cursor(
        self, task_id: str, *, execution_version: int,
        resource_id: str, member_id: str,
    ) -> bool:
        row = self._session.get(LibraryImportTask, task_id, populate_existing=True)
        if (
            row is None or row.kind != "IMPORT_BOOK" or row.state != "RUNNING"
            or row.phase != "RESOURCES" or row.execution_version != execution_version
            or (row.directory_resource_id not in (None, resource_id))
            or (row.directory_member_cursor is not None and member_id <= row.directory_member_cursor)
        ):
            return False
        advanced = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.directory_member_cursor == row.directory_member_cursor,
            )
            .values(directory_resource_id=resource_id, directory_member_cursor=member_id)
            .returning(LibraryImportTask.id)
        )
        return advanced is not None

    def advance_directory_cover_cursor(
        self, task_id: str, *, execution_version: int,
        resource_id: str, asset_id: str,
    ) -> bool:
        row = self._session.get(LibraryImportTask, task_id, populate_existing=True)
        if (
            row is None or row.kind != "IMPORT_BOOK" or row.state != "RUNNING"
            or row.phase != "RESOURCES" or row.execution_version != execution_version
            or row.directory_resource_id != resource_id
        ):
            return False
        changed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
                LibraryImportTask.directory_cover_cursor == row.directory_cover_cursor,
            )
            .values(directory_cover_cursor=asset_id)
            .returning(LibraryImportTask.id)
        )
        return changed is not None

    def advance_book_phase(
        self, task_id: str, *, execution_version: int, phase: str
    ) -> bool:
        if phase not in {"RESOURCES", "IDENTIFY"}:
            raise ValueError("INVALID_BOOK_PHASE")
        row = self._session.get(LibraryImportTask, task_id)
        gate: bool | None = None
        if row is not None and row.phase == "SCAN":
            node = self._session.get(LibrarySourceNode, row.source_node_id)
            if node is None:
                return False
            gate = book_gate_blocked(
                self._session,
                library_id=row.library_id,
                relative_path=node.relative_path,
                physical_kind=node.physical_kind,
                has_scan_work=False,
            )
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
            .values(**({"phase": phase, "scan_gate_blocked": gate} if gate is not None else {"phase": phase}))
            .returning(LibraryImportTask.id)
        )
        return advanced is not None

    def finish_book_run(
        self, task_id: str, *, execution_version: int, finished_at: datetime
    ) -> BookImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id)
        if (
            row is None or row.kind != "IMPORT_BOOK" or row.state != "RUNNING"
            or row.execution_version != execution_version
        ):
            return None
        if self._session.scalar(
            select(LibraryBookMetadata.metadata_pending).where(
                LibraryBookMetadata.book_id == row.book_id
            )
        ):
            raise ValueError("BOOK_IDENTIFICATION_PENDING")
        finished = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
            )
            .values(state="SUCCEEDED", phase="FINALIZE", finished_at=finished_at,
                    error_summary=None)
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
        failed_at: datetime,
        partial_failure: bool = False,
    ) -> BookImportTaskRecord | None:
        if not error_summary:
            raise ValueError("EMPTY_BOOK_FAILURE")
        row = self._session.get(LibraryImportTask, task_id)
        if (
            row is None or row.kind != "IMPORT_BOOK" or row.state != "RUNNING"
            or row.execution_version != execution_version
        ):
            return None
        if row.phase == "SCAN":
            work = decode_book_work(row.book_work or "").active
            scan_scopes = work.scan_scopes
            if scan_scopes is None:
                node = self._session.get(LibrarySourceNode, row.source_node_id)
                scan_scopes = (ScanScope(node.relative_path, True),) if node else ()
            if scan_scopes:
                record_scan_gaps(self._session, row.library_id, scan_scopes)
        failed = self._session.scalar(
            update(LibraryImportTask)
            .where(
                LibraryImportTask.id == task_id,
                LibraryImportTask.kind == "IMPORT_BOOK",
                LibraryImportTask.state == "RUNNING",
                LibraryImportTask.execution_version == execution_version,
            )
            .values(state="FAILED", finished_at=failed_at,
                    error_summary=error_summary)
            .returning(LibraryImportTask.id)
        )
        if failed is None:
            return None
        if not partial_failure:
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
        previous = self._session.get(LibraryImportTask, task_id)
        if previous is None:
            raise LookupError(task_id)
        book_id = previous.book_id
        if book_id is None and previous.resource_id is not None:
            resource = self._session.get(LibraryReadableResource, previous.resource_id)
            if resource is None or resource.library_id != previous.library_id:
                raise LookupError(task_id)
            book_id = resource.book_id
        if book_id is None and previous.superseded_by_task_id is not None:
            historical = self._session.get(LibraryImportTask, previous.superseded_by_task_id)
            book_id = None if historical is None else historical.book_id
        if book_id is None:
            return None
        book = self._session.get(LibraryBook, book_id)
        if book is None or book.library_id != previous.library_id:
            raise LookupError(task_id)
        if force:
            if previous.resource_id is None:
                raise ValueError("FORCE_REQUIRES_RESOURCE_TASK")
            work = BookWork(
                resource_ids=(previous.resource_id,), reasons=("FORCE_REIMPORT",),
            )
        elif previous.kind == "IMPORT_BOOK":
            previous_work = decode_book_work(previous.book_work or "")
            work = previous_work.active if not previous_work.active.is_empty else previous_work.pending
            if work.is_empty:
                work = BookWork(scan_scopes=None, resource_ids=None, identify=True)
        elif previous.resource_id is not None:
            work = BookWork(resource_ids=(previous.resource_id,), identify=True)
        else:
            work = BookWork(identify=True)
        task = self.request_book_work(
            book_id=book_id, work=work, requested_at=continued_at,
        )
        return task, True

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
        # A scan request owns its scope; historical and running scans are immutable.
        row = LibraryImportTask(
            id=cuid(),
            kind="SCAN_LIBRARY",
            library_id=library_id,
            state="QUEUED",
            missing_entry_policy=missing_entry_policy.value,
            scan_scopes=encode_scan_scopes(scan_scopes),
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row), True

    def request_source_scan(
        self,
        *,
        library_id: str,
        source_node_id: str,
        missing_entry_policy: MissingEntryPolicy,
    ) -> tuple[LibraryImportTaskRecord, bool]:
        node = self._session.get(LibrarySourceNode, source_node_id)
        if node is None or node.library_id != library_id:
            raise LookupError(source_node_id)
        task = self.enqueue(
            kind="CONTINUE_SOURCE",
            library_id=library_id,
            source_node_id=source_node_id,
            missing_entry_policy=missing_entry_policy,
        )
        return task, True

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

    def next_queued(self, *, started_at: datetime | None = None) -> LibraryImportTaskRecord | None:
        """Select the oldest not-yet-started import, regardless of kind."""
        row = self._session.scalar(
            select(LibraryImportTask)
            .where(
                LibraryImportTask.kind.in_(("SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_BOOK")),
                LibraryImportTask.state == "QUEUED",
                LibraryImportTask.superseded_by_task_id.is_(None),
                ~file_operation_blocks_library(LibraryImportTask.library_id),
            )
            .order_by(
                LibraryImportTask.created_at.asc(),
                LibraryImportTask.id.asc(),
            )
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return None if row is None else self._to_record(row)

    def get_task(self, task_id: str) -> LibraryImportTaskRecord | None:
        row = self._session.get(LibraryImportTask, task_id, populate_existing=True)
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
        row.started_at = started_at
        row.error_summary = None
        self._session.flush()

    def mark_succeeded(self, task_id: str, *, finished_at: datetime) -> None:
        changed = self._session.scalar(
            update(LibraryImportTask)
            .where(LibraryImportTask.id == task_id, LibraryImportTask.state == "RUNNING")
            .values(state="SUCCEEDED", finished_at=finished_at, error_summary=None)
            .returning(LibraryImportTask.id)
        )
        if changed is None:
            raise ValueError("IMPORT_TASK_NOT_RUNNING")

    def mark_failed(
        self,
        task_id: str,
        *,
        error_summary: str,
        finished_at: datetime,
    ) -> None:
        row = self._session.get(LibraryImportTask, task_id)
        if row is None or row.state != "RUNNING":
            raise ValueError("IMPORT_TASK_NOT_RUNNING")
        if row.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
            self._record_gaps_for_task(row)
        changed = self._session.scalar(
            update(LibraryImportTask)
            .where(LibraryImportTask.id == task_id, LibraryImportTask.state == "RUNNING")
            .values(state="FAILED", finished_at=finished_at,
                    error_summary=error_summary)
            .returning(LibraryImportTask.id)
        )
        if changed is None:
            raise ValueError("IMPORT_TASK_NOT_RUNNING")
        self._completion.finished(row)

    def fail_interrupted_tasks_on_startup(self, *, finished_at: datetime) -> int:
        running = self._session.scalars(
            select(LibraryImportTask).where(LibraryImportTask.state == "RUNNING")
        ).all()
        for task in running:
            prepare_exception_diagnostic(
                logging.getLogger(__name__), "import.task_interrupted",
                ImportTaskInterrupted(
                    "Startup observed a persisted RUNNING task without its executor"
                ),
                context={
                    "task_id": task.id, "task_kind": task.kind,
                    "library_id": task.library_id, "resource_id": task.resource_id,
                    "source_node_id": task.source_node_id, "step": "startup_finalization",
                    "outcome": "FAILED", "code": WORKER_INTERRUPTED,
                },
            )
            if task.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
                self._record_gaps_for_task(task)
        result = self._session.execute(
            update(LibraryImportTask)
            .where(LibraryImportTask.state == "RUNNING")
            .values(state="FAILED", error_summary=WORKER_INTERRUPTED,
                    finished_at=finished_at)
        )
        return int(getattr(result, "rowcount", 0) or 0)

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
        if resolved_scopes or incomplete_scopes:
            refresh_book_gates(self._session)

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
