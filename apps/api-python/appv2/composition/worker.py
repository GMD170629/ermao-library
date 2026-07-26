from __future__ import annotations

import time
from dataclasses import dataclass

from appv2.composition.container import Container


@dataclass(slots=True)
class WorkerRuntime:
    container: Container
    worker_id: str
    scheduler_enabled: bool = True
    next_reconciliation_at: float = 0
    next_metadata_schedule_at: float = 0

    def run_once(self) -> bool:
        handled = False
        disabled = self.container.operations.disabled_queues()
        if "ingestion" not in disabled:
            now = time.monotonic()
            if self.scheduler_enabled and now >= self.next_reconciliation_at:
                self.container.ingestion.request_scan(
                    trigger="periodic",
                    monitor_folder_id=None,
                    requested_by=None,
                )
                self.next_reconciliation_at = (
                    now + self.container.settings.monitor_refresh_interval_ms / 1000
                )
            if self.scheduler_enabled:
                handled = self.container.ingestion_scanner.run_once() or handled
            handled = self.container.ingestion_worker.run_once(self.worker_id) or handled
            handled = self.container.ingestion_outbox.run_once() or handled
        if "metadata" not in disabled:
            now = time.monotonic()
            if self.scheduler_enabled and now >= self.next_metadata_schedule_at:
                created, interval_minutes = self.container.metadata.schedule_interval()
                handled = created > 0 or handled
                self.next_metadata_schedule_at = now + (
                    interval_minutes * 60 if interval_minutes is not None else 60
                )
            handled = self.container.metadata_worker.run_once(self.worker_id) or handled
        if "discovery" not in disabled:
            handled = self.container.discovery_worker.run_once(self.worker_id) or handled
        if "delivery" not in disabled:
            handled = self.container.delivery_worker.run_once(self.worker_id) or handled
        if "backups" not in disabled:
            handled = self.container.backup_worker.run_once() or handled
        return handled
