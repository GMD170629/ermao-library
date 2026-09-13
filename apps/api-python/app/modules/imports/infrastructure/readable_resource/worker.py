"""Single-consumer worker for ADR 0018 ContinueImport tasks."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import SQLAlchemyError

from app.modules.imports.application.readable_resource.ports import (
    ClockPort,
    LibraryImportTaskQueuePort,
    LibraryImportTaskRecord,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
    SourceScanStartUnavailableError,
)
from app.modules.library.public import IdentifyImportedBook

logger = logging.getLogger("ermao.readable_resource_pipeline")


@dataclass(frozen=True, slots=True)
class _PendingCompletion:
    task_id: str
    library_id: str
    finished_at: datetime
    outcome: str
    error_summary: str | None = None


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
    ) -> None:
        self._queue = queue
        self._scan = scan
        self._process_import = process_import
        self._uow = uow
        self._clock = clock
        self._identify_book = identify_book
        self._pending_completion: _PendingCompletion | None = None

    def startup(self) -> int:
        finished_at = self._clock.now()
        with self._uow.transaction():
            return self._queue.fail_interrupted_tasks_on_startup(
                finished_at=finished_at
            )

    def recover_after_loop_failure(self) -> None:
        """Reset a failed unit of work before the process loop continues."""

        self._uow.rollback()

    def process_once(self) -> str:
        # A claimed task remains owned until its terminal state is committed.
        # Retrying this write must never rerun scanning, parsing, or metadata I/O.
        if self._pending_completion is not None:
            return self._finish_pending_completion()

        identification_deferred = not self._enqueue_ready_books()
        started_at = self._clock.now()
        with self._uow.transaction():
            task = self._queue.next_queued()
            if task is not None:
                self._queue.mark_running(task.id, started_at=started_at)
        if task is None:
            self._process_import.reset_inspection_cache()
            return "deferred" if identification_deferred else "idle"

        try:
            outcome = self._execute_task(task)
            pending = _PendingCompletion(
                task.id,
                task.library_id,
                self._clock.now(),
                outcome,
                "UNKNOWN_KIND" if outcome == "unknown_kind" else None,
            )
        except Exception as error:
            self._uow.rollback()
            logger.exception(
                "readable_resource.worker.containment_failure",
                extra={
                    "stage": "worker",
                    "outcome": "error",
                    "task_id": task.id,
                    "library_id": task.library_id,
                },
            )
            pending = _PendingCompletion(
                task.id,
                task.library_id,
                self._clock.now(),
                "error",
                error.code
                if isinstance(error, SourceScanStartUnavailableError)
                else "WORKER_ERROR",
            )
        self._pending_completion = pending
        return self._finish_pending_completion()

    def _execute_task(self, task: LibraryImportTaskRecord) -> str:
        if task.kind in {"SCAN_LIBRARY", "CONTINUE_SOURCE"}:
            self._process_import.reset_inspection_cache()
        if task.kind == "SCAN_LIBRARY":
            self._scan.execute_library(
                task.library_id,
                task_id=task.id,
                missing_entry_policy=task.missing_entry_policy,
            )
            return "scan"
        if task.kind == "CONTINUE_SOURCE":
            if task.source_node_id is None:
                raise RuntimeError("CONTINUE_SOURCE missing source_node_id")
            self._scan.execute_source(
                task.source_node_id,
                task_id=task.id,
                missing_entry_policy=task.missing_entry_policy,
            )
            return "continue_source"
        if task.kind == "IDENTIFY_BOOK":
            if self._identify_book is None or task.source_node_id is None:
                raise RuntimeError("Book metadata processor is not configured")
            return self._identify_book.execute(task.source_node_id)
        if task.kind == "IMPORT_ASSET":
            return self._process_import.execute(task.id).outcome
        return "unknown_kind"

    def _finish_pending_completion(self) -> str:
        pending = self._pending_completion
        if pending is None:
            raise RuntimeError("No claimed task is awaiting completion")
        try:
            with self._uow.transaction():
                current = self._queue.get_task(pending.task_id)
                if current is not None and current.state == "RUNNING":
                    if pending.error_summary is None:
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
            self._uow.rollback()
            logger.warning(
                "readable_resource.worker.completion_deferred "
                "task_id=%s library_id=%s error_type=%s",
                pending.task_id,
                pending.library_id,
                type(error).__name__,
            )
            return "deferred"
        self._pending_completion = None
        return "cancelled" if current is None else pending.outcome

    def _enqueue_ready_books(self) -> bool:
        # metadataPending is the durable compensation intent. Preparation and
        # ID allocation precede the SQL-only write scope; failed batches remain
        # discoverable on the next loop and after a process restart.
        try:
            prepared = self._queue.prepare_book_identifications()
            self._uow.release_before_io()
            if prepared:
                with self._uow.transaction():
                    self._queue.enqueue_book_identifications(prepared)
            return True
        except SQLAlchemyError as error:
            self._uow.rollback()
            logger.warning(
                "readable_resource.worker.identification_deferred error_type=%s",
                type(error).__name__,
            )
            return False


__all__ = ["ReadableResourceWorkerProcessor"]
