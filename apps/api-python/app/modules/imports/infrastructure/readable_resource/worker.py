"""Target overlay worker processor (application orchestration, not production entry)."""

from __future__ import annotations

import logging

from app.modules.imports.application.readable_resource.ports import UnitOfWorkPort
from app.modules.imports.application.readable_resource.process_import_task import (
    ProcessReadableResourceImportTask,
)
from app.modules.imports.application.readable_resource.scan_source_tree import (
    ScanLibrarySourceTree,
)
from app.modules.imports.application.readable_resource.ports import WorkQueuePort

logger = logging.getLogger("ermao.readable_resource_pipeline")


class ReadableResourceWorkerProcessor:
    """Claim overlay work and dispatch use cases; containment rollbacks via UoW port."""

    def __init__(
        self,
        *,
        queue: WorkQueuePort,
        scan: ScanLibrarySourceTree,
        process_import: ProcessReadableResourceImportTask,
        uow: UnitOfWorkPort,
        worker_id: str,
    ) -> None:
        self._queue = queue
        self._scan = scan
        self._process_import = process_import
        self._uow = uow
        self._worker_id = worker_id

    def process_once(self, *, lease_seconds: int = 120) -> str:
        claimed = self._queue.claim_next(self._worker_id, lease_seconds=lease_seconds)
        if claimed is None:
            return "idle"
        try:
            if claimed.work_kind == "scan":
                result = self._scan.execute(
                    claimed.target_id, claimed, lease_seconds=min(lease_seconds, 60)
                )
                if result.stopped_for_lease:
                    return "lease_lost"
                with self._uow.transaction():
                    if not self._queue.complete(claimed):
                        return "lease_lost"
                return "scan"
            outcome = self._process_import.execute(
                claimed.target_id, claimed, lease_seconds=lease_seconds
            )
            return outcome.outcome
        except Exception:
            self._uow.rollback()
            logger.exception(
                "readable_resource.worker.containment_failure",
                extra={"stage": "worker", "outcome": "error"},
            )
            return "error"
