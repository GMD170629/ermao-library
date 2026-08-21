"""ContinueImport — unified continue-import entry for ADR 0018."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.imports.application.readable_resource.ports import (
    LibraryConfigPort,
    PipelineLogPort,
    SourceNodeRepositoryPort,
    UnitOfWorkPort,
    LibraryImportTaskQueuePort,
)


@dataclass(frozen=True, slots=True)
class ContinueLibraryImport:
    library_id: str


@dataclass(frozen=True, slots=True)
class ContinueSourceImport:
    source_node_id: str


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
        libraries: LibraryConfigPort,
        source_nodes: SourceNodeRepositoryPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        log: PipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._source_nodes = source_nodes
        self._queue = queue
        self._uow = uow
        self._log = log

    def execute(
        self,
        target: ContinueLibraryImport | ContinueSourceImport,
    ) -> ContinueImportResult:
        if isinstance(target, ContinueLibraryImport):
            return self._continue_library(target.library_id)
        return self._continue_source(target.source_node_id)

    def _continue_library(self, library_id: str) -> ContinueImportResult:
        with self._uow.transaction():
            self._libraries.get_library(library_id)
            requeued = self._queue.requeue_failed_for_library(library_id)
            enqueued = False
            task_id: str | None = None
            if not self._queue.has_active_kind(
                kind="SCAN_LIBRARY", library_id=library_id
            ):
                task = self._queue.enqueue(
                    kind="SCAN_LIBRARY", library_id=library_id
                )
                enqueued = True
                task_id = task.id
        self._log.emit(
            "continue_import.library",
            library_id=library_id,
            stage="continue",
            outcome="enqueued" if enqueued else "already_active",
        )
        return ContinueImportResult(
            library_id=library_id,
            source_node_id=None,
            requeued_failed=requeued,
            enqueued_scan=enqueued,
            task_id=task_id,
        )

    def _continue_source(self, source_node_id: str) -> ContinueImportResult:
        with self._uow.transaction():
            node = self._source_nodes.get(source_node_id)
            if node is None:
                raise LookupError(source_node_id)
            library_id = node.library_id
            requeued = self._queue.requeue_failed_for_source(source_node_id)
            # Also requeue FAILED IMPORT_ASSET under resources in this subtree
            # when continuing a directory: scan will ensure_import_asset_task.
            # For FAILED asset tasks whose source_node is in subtree, reset them
            # via library-scoped filter is too broad; CONTINUE_SOURCE scan uses
            # ensure_import_asset_task which resets FAILED per asset.
            enqueued = False
            task_id: str | None = None
            if not self._queue.has_active_kind(
                kind="CONTINUE_SOURCE",
                library_id=library_id,
                source_node_id=source_node_id,
            ):
                task = self._queue.enqueue(
                    kind="CONTINUE_SOURCE",
                    library_id=library_id,
                    source_node_id=source_node_id,
                )
                enqueued = True
                task_id = task.id
        self._log.emit(
            "continue_import.source",
            library_id=library_id,
            stage="continue",
            outcome="enqueued" if enqueued else "already_active",
        )
        return ContinueImportResult(
            library_id=library_id,
            source_node_id=source_node_id,
            requeued_failed=requeued,
            enqueued_scan=enqueued,
            task_id=task_id,
        )


__all__ = [
    "ContinueImport",
    "ContinueImportResult",
    "ContinueLibraryImport",
    "ContinueSourceImport",
]
