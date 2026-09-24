"""ContinueImport — unified continue-import entry for ADR 0018."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    BookImportTaskQueuePort,
    ClockPort,
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
    force: bool = False


@dataclass(frozen=True, slots=True)
class ContinueImportResult:
    library_id: str
    source_node_id: str | None
    enqueued: bool
    task_id: str | None


class ContinueImport:
    """Create a fresh task for the requested library, source, or historical target."""

    def __init__(
        self,
        *,
        source_nodes: SourceNodeRepositoryPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        log: PipelineLogPort,
        request_library_scan: RequestLibraryScan | None = None,
        book_queue: BookImportTaskQueuePort | None = None,
        clock: ClockPort | None = None,
    ) -> None:
        self._source_nodes = source_nodes
        self._queue = queue
        self._uow = uow
        self._log = log
        self._request_library_scan = request_library_scan
        self._book_queue = book_queue
        self._clock = clock

    def execute(
        self,
        target: ContinueLibraryImport | ContinueSourceImport | ContinueImportTask,
    ) -> ContinueImportResult:
        if isinstance(target, ContinueLibraryImport):
            return self._continue_library(target.library_id)
        if isinstance(target, ContinueImportTask):
            return self._continue_task(target.task_id, force=target.force)
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
            enqueued=result.enqueued,
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
            enqueued=enqueued,
            task_id=task.id,
        )

    def _continue_task(
        self, task_id: str, *, force: bool = False
    ) -> ContinueImportResult:
        book_result = None
        with self._uow.transaction():
            if self._book_queue is not None:
                if self._clock is None:
                    raise RuntimeError("Book task clock is not configured")
                book_result = self._book_queue.continue_book_task(
                    task_id, continued_at=self._clock.now(), force=force
                )
            if book_result is None:
                existing = self._queue.get_task(task_id)
                if existing is None:
                    raise LookupError(task_id)
                if existing.kind == "SCAN_LIBRARY":
                    task, _ = self._queue.request_library_scan(
                        existing.library_id,
                        missing_entry_policy=existing.missing_entry_policy,
                        scan_scopes=existing.scan_scopes,
                    )
                elif existing.kind == "CONTINUE_SOURCE" and existing.source_node_id:
                    task, _ = self._queue.request_source_scan(
                        library_id=existing.library_id,
                        source_node_id=existing.source_node_id,
                        missing_entry_policy=existing.missing_entry_policy,
                    )
                else:
                    raise LookupError(task_id)
        if book_result is not None:
            book_task, _ = book_result
            self._log.emit(
                "continue_import.task",
                library_id=book_task.library_id,
                task_id=book_task.id,
                stage="continue",
                outcome="enqueued",
            )
            return ContinueImportResult(
                library_id=book_task.library_id,
                source_node_id=book_task.source_node_id,
                enqueued=True,
                task_id=book_task.id,
            )
        self._log.emit(
            "continue_import.task",
            library_id=task.library_id,
            task_id=task.id,
            stage="continue",
            outcome="enqueued",
        )
        return ContinueImportResult(
            library_id=task.library_id,
            source_node_id=task.source_node_id,
            enqueued=True,
            task_id=task.id,
        )


__all__ = [
    "ContinueImport",
    "ContinueImportResult",
    "ContinueImportTask",
    "ContinueLibraryImport",
    "ContinueSourceImport",
]
