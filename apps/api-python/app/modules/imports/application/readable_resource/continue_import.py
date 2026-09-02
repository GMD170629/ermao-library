"""ContinueImport — unified continue-import entry for ADR 0018."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    LibraryImportTaskQueuePort,
    PipelineLogPort,
    SourceNodeRepositoryPort,
    UnitOfWorkPort,
)
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScan,
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy


@dataclass(frozen=True, slots=True)
class ContinueLibraryImport:
    library_id: str


@dataclass(frozen=True, slots=True)
class ContinueSourceImport:
    source_node_id: str
    missing_entry_policy: MissingEntryPolicy = MissingEntryPolicy.PRESERVE


@dataclass(frozen=True, slots=True)
class ContinueImportTask:
    task_id: str


@dataclass(frozen=True, slots=True)
class ContinueImportResult:
    library_id: str
    source_node_id: str | None
    requeued_failed: int
    enqueued_scan: bool
    task_id: str | None


class ContinueImport:
    """Enqueue SCAN_LIBRARY / CONTINUE_SOURCE and requeue FAILED tasks."""

    def __init__(
        self,
        *,
        source_nodes: SourceNodeRepositoryPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        log: PipelineLogPort,
        request_library_scan: RequestLibraryScan | None = None,
    ) -> None:
        self._source_nodes = source_nodes
        self._queue = queue
        self._uow = uow
        self._log = log
        self._request_library_scan = request_library_scan

    def execute(
        self,
        target: ContinueLibraryImport | ContinueSourceImport | ContinueImportTask,
    ) -> ContinueImportResult:
        if isinstance(target, ContinueLibraryImport):
            return self._continue_library(target.library_id)
        if isinstance(target, ContinueImportTask):
            return self._continue_task(target.task_id)
        return self._continue_source(target)

    def _continue_library(self, library_id: str) -> ContinueImportResult:
        if self._request_library_scan is None:
            raise RuntimeError("library scan requester is not configured")
        result = self._request_library_scan.execute(
            RequestLibraryScanCommand(library_id=library_id, trigger="MANUAL")
        )
        return ContinueImportResult(
            library_id=result.library_id,
            source_node_id=None,
            requeued_failed=0,
            enqueued_scan=result.enqueued,
            task_id=result.task_id,
        )

    def _continue_source(self, target: ContinueSourceImport) -> ContinueImportResult:
        source_node_id = target.source_node_id
        with self._uow.transaction():
            node = self._source_nodes.get(source_node_id)
            if node is None:
                raise LookupError(source_node_id)
            library_id = node.library_id
            task, enqueued = self._queue.request_source_scan(
                library_id=library_id,
                source_node_id=source_node_id,
                missing_entry_policy=target.missing_entry_policy,
            )
        self._log.emit(
            "continue_import.source",
            library_id=library_id,
            task_id=task.id,
            stage="continue",
            outcome="enqueued" if enqueued else "coalesced",
        )
        return ContinueImportResult(
            library_id=library_id,
            source_node_id=source_node_id,
            requeued_failed=0,
            enqueued_scan=enqueued,
            task_id=task.id,
        )

    def _continue_task(self, task_id: str) -> ContinueImportResult:
        with self._uow.transaction():
            existing = self._queue.get_task(task_id)
            if existing is None or existing.source_node_id is None:
                raise LookupError(task_id)
            task, requeued = self._queue.requeue_failed_task(task_id)
        self._log.emit(
            "continue_import.task",
            library_id=task.library_id,
            task_id=task.id,
            stage="continue",
            outcome="requeued" if requeued else "not_failed",
        )
        return ContinueImportResult(
            library_id=task.library_id,
            source_node_id=task.source_node_id,
            requeued_failed=1 if requeued else 0,
            enqueued_scan=requeued,
            task_id=task.id if requeued else None,
        )


__all__ = [
    "ContinueImport",
    "ContinueImportResult",
    "ContinueImportTask",
    "ContinueLibraryImport",
    "ContinueSourceImport",
]
