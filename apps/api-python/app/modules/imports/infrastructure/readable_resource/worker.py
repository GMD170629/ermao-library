"""Single-consumer worker for ADR 0018 ContinueImport tasks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.contracts.library_file_activity import LibraryFileActivityBusy
from app.core.database_errors import is_retryable_sqlite_operation_error
from app.core.exception_diagnostics import (
    deferred_exception_persistence,
    exception_diagnostic_boundary,
    persist_exception_diagnostic,
    prepare_exception_diagnostic,
)
from app.modules.imports.application.readable_resource.ports import (
    BookImportTaskQueuePort,
    BookImportTaskRecord,
    ClockPort,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.process_book_resources import (
    ProcessBookResources,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
    SourceScanStartUnavailableError,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy
from app.modules.library.public import IdentifyImportedBook

logger = logging.getLogger("ermao.readable_resource_pipeline")


@dataclass(frozen=True, slots=True)
class _PendingCompletion:
    task_id: str
    library_id: str
    finished_at: datetime
    outcome: str
    error_summary: str | None = None
    execution_version: int | None = None
    partial_failure: bool = False


class ReadableResourceWorkerProcessor:
    """Strict single-consumer loop with deterministic FIFO ordering."""

    def __init__(
        self,
        *,
        queue: LibraryImportTaskQueuePort,
        scan: ScanLibrarySourceTree,
        process_import: ProcessReadableResourceImportTask,
        uow: UnitOfWorkPort,
        clock: ClockPort,
        identify_book: IdentifyImportedBook | None = None,
        book_queue: BookImportTaskQueuePort | None = None,
        process_book_resources: ProcessBookResources | None = None,
    ) -> None:
        if (book_queue is None) != (process_book_resources is None):
            raise ValueError("BOOK_WORKER_INCOMPLETE_CONFIGURATION")
        self._queue = queue
        self._scan = scan
        self._process_import = process_import
        self._uow = uow
        self._clock = clock
        self._identify_book = identify_book
        self._book_queue = book_queue
        self._process_book_resources = process_book_resources
        self._pending_completion: _PendingCompletion | None = None
        self._pending_discovery_completion: _PendingCompletion | None = None

    def startup(self) -> int:
        finished_at = self._clock.now()
        with exception_diagnostic_boundary(logger, "readable_resource.startup_failed", context={"step": "startup_recovery"}), self._uow.transaction():
            return self._queue.fail_interrupted_tasks_on_startup(
                finished_at=finished_at
            )

    def recover_after_loop_failure(self) -> None:
        """Reset a failed unit of work before the process loop continues."""

        self._uow.rollback()

    def process_once(self) -> str:
        # A claimed task remains owned until its terminal state is committed.
        # Retrying this write must never rerun scanning, parsing, or metadata I/O.
        with exception_diagnostic_boundary(logger, "readable_resource.worker.failed", context={}):
            if self._pending_completion is not None:
                return self._finish_pending_completion()
            if self._pending_discovery_completion is not None:
                self._pending_completion = self._pending_discovery_completion
                self._pending_discovery_completion = None
                return self._finish_pending_completion()

            started_at = self._clock.now()
            try:
                with self._uow.transaction():
                    book = (
                        self._book_queue.claim_next_book(started_at=started_at)
                        if self._book_queue is not None
                        else None
                    )
                    task = None if book is not None else self._queue.next_queued()
                    if book is None and task is not None:
                        self._queue.mark_running(task.id, started_at=started_at)
            except LibraryFileActivityBusy:
                # diagnostics-control-flow: The active file operation owns the lease; defer this import without failing it.
                return "deferred"
            if book is not None:
                return self._process_book(book)
            if task is None:
                self._process_import.reset_inspection_cache()
                return "idle"

            try:
                outcome = self._execute_task(task)
                pending = _PendingCompletion(
                    task.id,
                    task.library_id,
                    self._clock.now(),
                    outcome,
                    "UNKNOWN_KIND" if outcome == "unknown_kind" else None,
                )
            except Exception as error:  # noqa: BLE001 - task containment boundary
                # Preserve the original failure before rollback or cleanup so a
                # failing rollback cannot mask the root cause.
                scan_error = error if isinstance(error, SourceScanStartUnavailableError) else None
                event = (
                    "readable_resource.worker.scan_failed"
                    if scan_error is not None
                    else "readable_resource.worker.containment_failure"
                )
                snapshot = prepare_exception_diagnostic(
                    logger,
                    event,
                    error,
                    level="warning" if scan_error is not None else "error",
                    context={
                        "stage": "scan" if scan_error is not None else "worker",
                        "outcome": scan_error.code if scan_error is not None else "error",
                        "task_id": task.id,
                        "task_kind": task.kind,
                        "library_id": task.library_id,
                        "resource_id": task.resource_id,
                        "source_node_id": task.source_node_id,
                    },
                    source="import",
                    action="readable_resource.task_failed",
                    target_type="importTask",
                    target_id=task.id,
                )
                try:
                    self._uow.rollback()
                finally:
                    # Persist only after the business transaction released its lock.
                    persist_exception_diagnostic(logger, snapshot)
                pending = _PendingCompletion(
                    task.id,
                    task.library_id,
                    self._clock.now(),
                    "error",
                    scan_error.code
                    if scan_error is not None
                    else "WORKER_ERROR",
                )
            if self._pending_completion is not None:
                self._pending_discovery_completion = pending
                return self._finish_pending_completion()
            self._pending_completion = pending
            return self._finish_pending_completion()

    def _process_discovered_book(self) -> None:
        if self._book_queue is None or self._pending_completion is not None:
            return
        try:
            with self._uow.transaction():
                book = self._book_queue.claim_next_book(started_at=self._clock.now())
        except LibraryFileActivityBusy:
            # diagnostics-control-flow: an active file operation owns this lease, so discovery defers Book claim.
            return
        except SQLAlchemyError as error:
            snapshot = prepare_exception_diagnostic(
                logger,
                "readable_resource.worker.discovery_book_claim_failed",
                error,
                level="warning" if is_retryable_sqlite_operation_error(error) else "error",
                context={"stage": "discovery_book_claim"},
                source="import",
                action="readable_resource.book_claim_failed",
            )
            try:
                self._uow.rollback()
            finally:
                persist_exception_diagnostic(logger, snapshot)
            if is_retryable_sqlite_operation_error(error):
                return
            raise
        if book is not None:
            self._process_book(book)

    def _process_book(self, book: BookImportTaskRecord) -> str:
        try:
            outcome, error_summary = self._execute_book(book)
            partial_failure = outcome == "book_partial_failure"
            if partial_failure:
                outcome = "failed"
        except Exception as error:  # noqa: BLE001 - task containment boundary
            scan_error = error if isinstance(error, SourceScanStartUnavailableError) else None
            snapshot = prepare_exception_diagnostic(
                logger,
                "readable_resource.worker.scan_failed"
                if scan_error is not None
                else "readable_resource.worker.containment_failure",
                error,
                level="warning" if scan_error is not None else "error",
                context={
                    "stage": "scan" if scan_error is not None else "worker",
                    "outcome": scan_error.code if scan_error is not None else "error",
                    "task_id": book.id,
                    "task_kind": "IMPORT_BOOK",
                    "library_id": book.library_id,
                    "book_id": book.book_id,
                    "source_node_id": book.source_node_id,
                },
                source="import",
                action="readable_resource.task_failed",
                target_type="importTask",
                target_id=book.id,
            )
            try:
                self._uow.rollback()
            finally:
                persist_exception_diagnostic(logger, snapshot)
            outcome = "error"
            error_summary = scan_error.code if scan_error is not None else "WORKER_ERROR"
            partial_failure = False
        self._pending_completion = _PendingCompletion(
            book.id,
            book.library_id,
            self._clock.now(),
            outcome,
            error_summary,
            book.execution_version,
            partial_failure,
        )
        return self._finish_pending_completion()

    def _execute_book(self, book: BookImportTaskRecord) -> tuple[str, str | None]:
        book_queue = self._book_queue
        if book_queue is None or self._process_book_resources is None:
            raise RuntimeError("Book worker is not configured")
        if book.execution_version is None:
            raise ValueError("BOOK_RUN_VERSION_MISSING")
        with deferred_exception_persistence(
            context={
                "task_id": book.id,
                "library_id": book.library_id,
                "task_kind": "IMPORT_BOOK",
                "book_id": book.book_id,
            }
        ):
            work = book.work.active
            phase = book.phase
            partial_error: str | None = None
            if phase == "SCAN":
                self._process_import.reset_inspection_cache()
                if work.scan_scopes is None:
                    self._scan.execute_source(
                        book.source_node_id,
                        task_id=book.id,
                        missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    )
                else:
                    self._scan.execute_library(
                        book.library_id,
                        task_id=book.id,
                        scan_scopes=work.scan_scopes,
                        missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    )
                phase = "RESOURCES" if work.resource_ids != () else "IDENTIFY"
                with self._uow.transaction():
                    if not book_queue.advance_book_phase(
                        book.id, execution_version=book.execution_version, phase=phase
                    ):
                        return "cancelled", None
            if phase == "RESOURCES":
                result = self._process_book_resources.execute(
                    book, max_resources=128
                )
                if result.outcome == "yielded":
                    return "book_yield", None
                if result.outcome == "failed":
                    return (
                        "failed",
                        result.error_summary or "BOOK_RESOURCE_STALE",
                    )
                if result.outcome == "cancelled":
                    return "cancelled", "BOOK_RESOURCE_STALE"
                if result.outcome == "partial":
                    partial_error = result.error_summary
                with self._uow.transaction():
                    if not book_queue.advance_book_phase(
                        book.id,
                        execution_version=book.execution_version,
                        phase="IDENTIFY",
                    ):
                        return "cancelled", None
            current = book_queue.get_book_task(book.id)
            if current is None:
                return "cancelled", None
            if not current.work.pending.is_empty:
                if partial_error is not None:
                    return "book_partial_failure", partial_error
                return "book_follow_up", None
            if self._identify_book is None:
                raise RuntimeError("Book metadata processor is not configured")
            def run_current() -> bool:
                return book_queue.book_run_is_current(
                    book.id,
                    execution_version=book.execution_version,
                    require_latest_request=True,
                )
            identified = self._identify_book.execute(
                book.source_node_id, book_run_current=run_current
            )
            if identified == "stale":
                current = book_queue.get_book_task(book.id)
                if current is not None and not current.work.pending.is_empty:
                    return "book_follow_up", None
                if book_queue.book_identification_complete(book.book_id):
                    failure = partial_error or self._process_book_resources.failure_summary(book.book_id)
                    if failure is not None:
                        return "book_partial_failure", failure
                    return "book", None
                return "error", "IDENTIFICATION_STALE"
            failure = partial_error or self._process_book_resources.failure_summary(book.book_id)
            if failure is not None:
                return "book_partial_failure", failure
            return "book", None

    def _execute_task(self, task: LibraryImportTaskRecord) -> str:
        with deferred_exception_persistence(context={"task_id": task.id, "library_id": task.library_id, "task_kind": task.kind, "resource_id": task.resource_id, "source_node_id": task.source_node_id}):
            batch_callback = (
                {"after_batch": self._process_discovered_book}
                if self._book_queue is not None
                else {}
            )
            if task.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
                self._process_import.reset_inspection_cache()
            if task.kind == "SCAN_LIBRARY":
                self._scan.execute_library(
                    task.library_id,
                    task_id=task.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    scan_scopes=task.scan_scopes,
                    **batch_callback,
                )
                return "scan"
            if task.kind == "CONTINUE_SOURCE":
                if task.source_node_id is None:
                    raise RuntimeError("CONTINUE_SOURCE missing source_node_id")
                self._scan.execute_source(
                    task.source_node_id,
                    task_id=task.id,
                    missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    **batch_callback,
                )
                return "continue_source"
            return "unknown_kind"

    def _finish_pending_completion(self) -> str:
        pending = self._pending_completion
        if pending is None:
            raise RuntimeError("No claimed task is awaiting completion")
        try:
            with self._uow.transaction():
                current = self._queue.get_task(pending.task_id)
                if current is not None and current.state == "RUNNING":
                    if pending.execution_version is not None:
                        if self._book_queue is None:
                            raise RuntimeError("Book worker is not configured")
                        if pending.outcome == "book_yield":
                            self._book_queue.yield_book_run(
                                pending.task_id,
                                execution_version=pending.execution_version,
                                yielded_at=pending.finished_at,
                            )
                        elif pending.error_summary is None:
                            self._book_queue.finish_book_run(
                                pending.task_id,
                                execution_version=pending.execution_version,
                                finished_at=pending.finished_at,
                            )
                        else:
                            self._book_queue.fail_book_run(
                                pending.task_id,
                                execution_version=pending.execution_version,
                                error_summary=pending.error_summary,
                                retryable=True,
                                failed_at=pending.finished_at,
                                partial_failure=pending.partial_failure,
                            )
                    elif pending.error_summary is None:
                        self._queue.mark_succeeded(
                            pending.task_id, finished_at=pending.finished_at
                        )
                    else:
                        self._queue.mark_failed(
                            pending.task_id,
                            error_summary=pending.error_summary,
                            finished_at=pending.finished_at,
                        )
        except SQLAlchemyError as error:
            snapshot = prepare_exception_diagnostic(
                logger,
                "readable_resource.worker.completion_deferred",
                error,
                level="warning",
                context={
                    "stage": "completion",
                    "outcome": "deferred",
                    "task_id": pending.task_id,
                    "library_id": pending.library_id,
                },
                source="import",
                action="readable_resource.completion_deferred",
                target_type="importTask",
                target_id=pending.task_id,
            )
            try:
                self._uow.rollback()
            finally:
                persist_exception_diagnostic(logger, snapshot)
            return "deferred"
        self._pending_completion = None
        return "cancelled" if current is None else pending.outcome

__all__ = ["ReadableResourceWorkerProcessor"]
