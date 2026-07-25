from __future__ import annotations

from dataclasses import dataclass

from appv2.composition.container import Container


@dataclass(slots=True)
class WorkerRuntime:
    container: Container
    worker_id: str

    def run_once(self) -> bool:
        handled = False
        handled = self.container.ingestion_worker.run_once(self.worker_id) or handled
        handled = self.container.metadata_worker.run_once(self.worker_id) or handled
        handled = self.container.discovery_worker.run_once(self.worker_id) or handled
        handled = self.container.delivery_worker.run_once(self.worker_id) or handled
        handled = self.container.backup_worker.run_once() or handled
        return handled
