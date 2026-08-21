"""Single-consumer worker for ADR 0018 ContinueImport tasks."""

from __future__ import annotations

import logging

from app.modules.imports.application.readable_resource.ports import (
    ClockPort,
    UnitOfWorkPort,
    WorkQueuePort,
)
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)

logger = logging.getLogger("ermao.readable_resource_pipeline")


class ReadableResourceWorkerProcessor:
    """Strict single-consumer loop: next QUEUED by createdAt, no lease/fencing."""

    def __init__(
        self,
        *,
        queue: WorkQueuePort,
        scan: ScanLibrarySourceTree,
        process_import: ProcessReadableResourceImportTask,
        uow: UnitOfWorkPort,
        clock: ClockPort,
    ) -> None:
        self._queue = queue
        self._scan = scan
        self._process_import = process_import
        self._uow = uow
        self._clock = clock

    def startup(self) -> int:
        with self._uow.transaction():
            return self._queue.fail_interrupted_tasks_on_startup(
                finished_at=self._clock.now()
            )

    def process_once(self) -> str:
        with self._uow.transaction():
            task = self._queue.next_queued()
            if task is None:
                return "idle"
            self._queue.mark_running(task.id, started_at=self._clock.now())
            task_id = task.id
            kind = task.kind
            library_id = task.library_id
            source_node_id = task.source_node_id

        try:
            if kind == "SCAN_LIBRARY":
                self._scan.execute_library(library_id)
                with self._uow.transaction():
                    self._queue.mark_succeeded(
                        task_id, finished_at=self._clock.now()
                    )
                return "scan"
            if kind == "CONTINUE_SOURCE":
                if source_node_id is None:
                    raise RuntimeError("CONTINUE_SOURCE missing source_node_id")
                self._scan.execute_source(source_node_id)
                with self._uow.transaction():
                    self._queue.mark_succeeded(
                        task_id, finished_at=self._clock.now()
                    )
                return "continue_source"
            if kind == "IMPORT_ASSET":
                outcome = self._process_import.execute(task_id)
                return outcome.outcome
            with self._uow.transaction():
                self._queue.mark_failed(
                    task_id,
                    error_summary="UNKNOWN_KIND",
                    finished_at=self._clock.now(),
                )
            return "unknown_kind"
        except Exception:
            self._uow.rollback()
            logger.exception(
                "readable_resource.worker.containment_failure",
                extra={
                    "stage": "worker",
                    "outcome": "error",
                    "task_id": task_id,
                },
            )
            with self._uow.transaction():
                current = self._queue.get_task(task_id)
                if current is not None and current.state == "RUNNING":
                    self._queue.mark_failed(
                        task_id,
                        error_summary="WORKER_ERROR",
                        finished_at=self._clock.now(),
                    )
            return "error"


__all__ = ["ReadableResourceWorkerProcessor"]
