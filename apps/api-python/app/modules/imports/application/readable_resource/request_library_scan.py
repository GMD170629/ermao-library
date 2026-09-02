"""Request one deduplicated library scan from any supported trigger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.modules.imports.application.readable_resource.ports import (
    LibraryConfigPort,
    LibraryImportTaskQueuePort,
    PipelineLogPort,
    UnitOfWorkPort,
)
from app.modules.imports.domain.scan_policy import MissingEntryPolicy

LibraryScanTrigger = Literal[
    "STARTUP",
    "WATCHER",
    "PERIODIC",
    "UPLOAD",
    "MANUAL",
    "ENABLE",
]


@dataclass(frozen=True, slots=True)
class RequestLibraryScanCommand:
    library_id: str
    trigger: LibraryScanTrigger


@dataclass(frozen=True, slots=True)
class RequestLibraryScanResult:
    library_id: str
    trigger: LibraryScanTrigger
    enqueued: bool
    task_id: str | None


class RequestLibraryScan:
    """Queue at most one follow-up scan while preserving a running scan."""

    def __init__(
        self,
        *,
        libraries: LibraryConfigPort,
        queue: LibraryImportTaskQueuePort,
        uow: UnitOfWorkPort,
        log: PipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._queue = queue
        self._uow = uow
        self._log = log

    def execute(self, command: RequestLibraryScanCommand) -> RequestLibraryScanResult:
        with self._uow.transaction():
            self._libraries.get_library(command.library_id)
            task, enqueued = self._queue.request_library_scan(
                command.library_id,
                missing_entry_policy=(
                    MissingEntryPolicy.PRUNE_MISSING
                    if command.trigger == "MANUAL"
                    else MissingEntryPolicy.PRESERVE
                ),
            )

        self._log.emit(
            "library_scan.requested",
            library_id=command.library_id,
            task_id=task.id,
            stage=command.trigger.lower(),
            outcome="enqueued" if enqueued else "coalesced",
        )
        return RequestLibraryScanResult(
            library_id=command.library_id,
            trigger=command.trigger,
            enqueued=enqueued,
            task_id=task.id,
        )


__all__ = [
    "LibraryScanTrigger",
    "RequestLibraryScan",
    "RequestLibraryScanCommand",
    "RequestLibraryScanResult",
]
