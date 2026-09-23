"""Single-consumer import worker: one claim, one execution, one terminal result."""

from __future__ import annotations

import logging

from app.contracts.library_file_activity import LibraryFileActivityBusy
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


class ReadableResourceWorkerProcessor:
    """Execute each accepted task at most once while preserving committed assets."""

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

    def startup(self) -> int:
        with exception_diagnostic_boundary(
            logger, "readable_resource.startup_failed",
            context={"step": "startup_finalization"},
        ), self._uow.transaction():
            return self._queue.fail_interrupted_tasks_on_startup(
                finished_at=self._clock.now()
            )

    def recover_after_loop_failure(self) -> None:
        self._uow.recover_after_failure()

    def process_once(self) -> str:
        with exception_diagnostic_boundary(
            logger, "readable_resource.worker.failed", context={}
        ):
            try:
                with self._uow.transaction():
                    task = self._queue.next_queued(started_at=self._clock.now())
                    book = None
                    if task is not None:
                        if task.kind == "IMPORT_BOOK":
                            if self._book_queue is None:
                                raise RuntimeError("Book worker is not configured")
                            book = self._book_queue.claim_book_task(
                                task.id, started_at=self._clock.now()
                            )
                        else:
                            self._queue.mark_running(
                                task.id, started_at=self._clock.now()
                            )
            except LibraryFileActivityBusy:
                # diagnostics-control-flow: the file operation still owns the target.
                return "idle"
            if task is None:
                self._process_import.reset_inspection_cache()
                return "idle"
            if task.kind == "IMPORT_BOOK":
                return "cancelled" if book is None else self._process_book(book)
            return self._process_discovery(task)

    def _record_execution_failure(
        self, error: Exception, task: LibraryImportTaskRecord | BookImportTaskRecord
    ) -> str:
        scan_error = error if isinstance(error, SourceScanStartUnavailableError) else None
        snapshot = prepare_exception_diagnostic(
            logger,
            "readable_resource.worker.scan_failed"
            if scan_error is not None
            else "readable_resource.worker.containment_failure",
            error,
            context={
                "stage": "scan" if scan_error is not None else "worker",
                "outcome": scan_error.code if scan_error is not None else "error",
                "task_id": task.id,
                "task_kind": "IMPORT_BOOK" if isinstance(task, BookImportTaskRecord)
                else task.kind,
                "library_id": task.library_id,
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
            persist_exception_diagnostic(logger, snapshot)
        return scan_error.code if scan_error is not None else "WORKER_ERROR"

    def _process_discovery(self, task: LibraryImportTaskRecord) -> str:
        try:
            outcome = self._execute_task(task)
            error_summary = "UNKNOWN_KIND" if outcome == "unknown_kind" else None
        except Exception as error:  # noqa: BLE001 - one task containment boundary
            error_summary = self._record_execution_failure(error, task)
            outcome = "error"
        return self._finish(
            task, outcome=outcome, error_summary=error_summary,
        )

    def _process_book(self, book: BookImportTaskRecord) -> str:
        if book.execution_version is None:
            raise RuntimeError("BOOK_RUN_VERSION_MISSING")
        try:
            outcome, error_summary = self._execute_book(book)
        except Exception as error:  # noqa: BLE001 - one Book containment boundary
            error_summary = self._record_execution_failure(error, book)
            outcome = "error"
        if outcome == "cancelled" and error_summary is None:
            return "cancelled"
        return self._finish(book, outcome=outcome, error_summary=error_summary)

    def _finish(
        self,
        task: LibraryImportTaskRecord | BookImportTaskRecord,
        *,
        outcome: str,
        error_summary: str | None,
    ) -> str:
        succeeded = error_summary is None
        try:
            with self._uow.transaction():
                current = self._queue.get_task(task.id)
                if current is None or current.state != "RUNNING":
                    return "cancelled"
                if isinstance(task, BookImportTaskRecord):
                    if self._book_queue is None or task.execution_version is None:
                        raise RuntimeError("BOOK_WORKER_INCOMPLETE_CONFIGURATION")
                    if succeeded:
                        written = self._book_queue.finish_book_run(
                            task.id, execution_version=task.execution_version,
                            finished_at=self._clock.now(),
                        )
                    else:
                        written = self._book_queue.fail_book_run(
                            task.id, execution_version=task.execution_version,
                            error_summary=error_summary,
                            failed_at=self._clock.now(),
                            partial_failure=outcome == "book_partial_failure",
                        )
                    if written is None:
                        raise ValueError("BOOK_TERMINAL_STATE_CONFLICT")
                elif succeeded:
                    self._queue.mark_succeeded(task.id, finished_at=self._clock.now())
                else:
                    self._queue.mark_failed(
                        task.id, error_summary=error_summary,
                        finished_at=self._clock.now(),
                    )
            return outcome if succeeded else "failed"
        except Exception as terminal_error:  # noqa: BLE001 - clean-context failure close
            snapshot = prepare_exception_diagnostic(
                logger, "readable_resource.worker.completion_write_failed",
                terminal_error,
                context={
                    "stage": "completion", "outcome": "failed_close",
                    "task_id": task.id, "library_id": task.library_id,
                    "task_kind": "IMPORT_BOOK" if isinstance(task, BookImportTaskRecord)
                    else task.kind,
                },
                source="import",
                action="readable_resource.completion_write_failed",
                target_type="importTask",
                target_id=task.id,
            )
            try:
                self._uow.recover_after_failure()
            finally:
                persist_exception_diagnostic(logger, snapshot)
            try:
                with self._uow.transaction():
                    current = self._queue.get_task(task.id)
                    if current is None:
                        return "cancelled"
                    if current.state == "SUCCEEDED":
                        return outcome
                    if current.state == "FAILED":
                        return "failed"
                    if current.state != "RUNNING":
                        raise ValueError("IMPORT_TERMINAL_STATE_CONFLICT")
                    summary = error_summary or (
                        "BOOK_COMPLETION_WRITE_FAILED"
                        if isinstance(task, BookImportTaskRecord)
                        else "TASK_COMPLETION_WRITE_FAILED"
                    )
                    if isinstance(task, BookImportTaskRecord):
                        assert self._book_queue is not None
                        assert task.execution_version is not None
                        if self._book_queue.fail_book_run(
                            task.id, execution_version=task.execution_version,
                            error_summary=summary, failed_at=self._clock.now(),
                        ) is None:
                            raise ValueError("BOOK_FAILURE_CLOSE_CONFLICT")
                    else:
                        self._queue.mark_failed(
                            task.id, error_summary=summary,
                            finished_at=self._clock.now(),
                        )
                return "failed"
            except Exception as close_error:
                secondary = prepare_exception_diagnostic(
                    logger, "readable_resource.worker.failure_close_failed",
                    close_error,
                    context={
                        "stage": "failure_close", "task_id": task.id,
                        "library_id": task.library_id,
                    },
                    source="import",
                    action="readable_resource.failure_close_failed",
                    target_type="importTask",
                    target_id=task.id,
                )
                try:
                    self._uow.recover_after_failure()
                finally:
                    persist_exception_diagnostic(logger, secondary)
                raise RuntimeError("IMPORT_TERMINAL_PERSISTENCE_FAILED") from close_error

    def _execute_book(self, book: BookImportTaskRecord) -> tuple[str, str | None]:
        queue = self._book_queue
        if queue is None or self._process_book_resources is None:
            raise RuntimeError("Book worker is not configured")
        assert book.execution_version is not None
        with deferred_exception_persistence(
            context={
                "task_id": book.id, "library_id": book.library_id,
                "task_kind": "IMPORT_BOOK", "book_id": book.book_id,
            }
        ):
            work = book.work.active
            phase = book.phase
            partial_error: str | None = None
            if phase == "SCAN":
                self._process_import.reset_inspection_cache()
                if work.scan_scopes is None:
                    self._scan.execute_source(
                        book.source_node_id, task_id=book.id,
                        missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    )
                else:
                    self._scan.execute_library(
                        book.library_id, task_id=book.id,
                        scan_scopes=work.scan_scopes,
                        missing_entry_policy=MissingEntryPolicy.PRUNE_MISSING,
                    )
                phase = "RESOURCES" if work.resource_ids != () else "IDENTIFY"
                with self._uow.transaction():
                    if not queue.advance_book_phase(
                        book.id, execution_version=book.execution_version,
                        phase=phase,
                    ):
                        return "cancelled", "BOOK_RUN_STALE"
            if phase == "RESOURCES":
                while True:
                    current = queue.get_book_task(book.id)
                    if current is None or current.state != "RUNNING":
                        return "cancelled", "BOOK_RUN_STALE"
                    result = self._process_book_resources.execute(
                        current, max_resources=128
                    )
                    if result.outcome != "yielded":
                        break
                if result.outcome == "failed":
                    return "failed", result.error_summary or "BOOK_RESOURCE_STALE"
                if result.outcome == "cancelled":
                    return "cancelled", "BOOK_RESOURCE_STALE"
                if result.outcome == "partial":
                    partial_error = result.error_summary
                with self._uow.transaction():
                    if not queue.advance_book_phase(
                        book.id, execution_version=book.execution_version,
                        phase="IDENTIFY",
                    ):
                        return "cancelled", "BOOK_RUN_STALE"
            if self._identify_book is None:
                raise RuntimeError("Book metadata processor is not configured")

            def run_current() -> bool:
                return queue.book_run_is_current(
                    book.id, execution_version=book.execution_version,
                    require_latest_request=True,
                )

            identified = self._identify_book.execute(
                book.source_node_id, book_run_current=run_current
            )
            if identified == "stale" and not queue.book_identification_complete(book.book_id):
                return "failed", "IDENTIFICATION_STALE"
            if partial_error is not None:
                return "book_partial_failure", partial_error
            return "book", None

    def _execute_task(self, task: LibraryImportTaskRecord) -> str:
        with deferred_exception_persistence(context={
            "task_id": task.id, "library_id": task.library_id,
            "task_kind": task.kind, "resource_id": task.resource_id,
            "source_node_id": task.source_node_id,
        }):
            if task.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
                self._process_import.reset_inspection_cache()
            if task.kind == "SCAN_LIBRARY":
                self._scan.execute_library(
                    task.library_id, task_id=task.id,
                    missing_entry_policy=task.missing_entry_policy,
                    scan_scopes=task.scan_scopes,
                )
                return "scan"
            if task.kind == "CONTINUE_SOURCE":
                if task.source_node_id is None:
                    raise RuntimeError("CONTINUE_SOURCE missing source_node_id")
                self._scan.execute_source(
                    task.source_node_id, task_id=task.id,
                    missing_entry_policy=task.missing_entry_policy,
                )
                return "continue_source"
            return "unknown_kind"


__all__ = ["ReadableResourceWorkerProcessor"]
