"""Thin persistent import worker loop.

Owns thread lifecycle and heartbeat only. Queue claim/process/fail/recover and
media import run through ``ImportWorkerRuntime`` (bootstrap composition root).
This module must not import Session, SQLAlchemy, ORM models, or field dictionaries.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from typing import Any

from app.bootstrap.imports import ImportWorkerRuntime
from app.core.config import Settings
from app.modules.imports.application.dto import ImportTaskDTO
from app.services.queue_runtime import QueueHeartbeatPump


class PersistentImportWorker:
    def __init__(
        self,
        runtime: ImportWorkerRuntime,
        settings: Settings,
        *,
        heartbeat_db_factory: Callable[[], Any],
        worker_id: str | None = None,
    ) -> None:
        self.runtime = runtime
        self.settings = settings
        self.worker_id = worker_id or f"import-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="shuku-persistent-import-worker",
            daemon=True,
        )
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory,
            queue_name="import",
            instance_id=self.worker_id,
            poll_interval_seconds=settings.import_queue_interval_seconds,
        )

    def start(self) -> None:
        recovered = self.runtime.recover()
        if recovered:
            print(
                f"[import-worker] recovered {recovered} stale import task(s)",
                flush=True,
            )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def process_once(self) -> bool:
        recovered = self.runtime.recover()
        lease_seconds = max(900, self.settings.ebook_conversion_timeout_seconds + 300)
        task = self.runtime.claim(self.worker_id, lease_seconds)
        if task is None:
            return bool(recovered)
        try:
            self.runtime.process(task)
        except Exception as exc:  # noqa: BLE001 — worker task containment boundary
            self.runtime.fail(task, exc)
            print(
                f"[import-worker] persistent task failed {task.id}: {exc}", flush=True
            )
        return True

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            while not self._stop_event.is_set():
                error = None
                processed = False
                try:
                    processed = self.process_once()
                except Exception as exc:  # noqa: BLE001 — worker loop containment boundary
                    error = exc
                self._heartbeat.pulse(processed=processed, error=error)
                if processed:
                    continue
                self._stop_event.wait(self.settings.import_queue_interval_seconds)
        finally:
            self._heartbeat.stop()


def start_persistent_import_worker(
    db_factory: Callable[[], Any],
    settings: Settings,
    heartbeat_db_factory: Callable[[], Any] | None = None,
) -> PersistentImportWorker:
    runtime = ImportWorkerRuntime(db_factory, settings)
    worker = PersistentImportWorker(
        runtime,
        settings,
        heartbeat_db_factory=heartbeat_db_factory or db_factory,
    )
    worker.start()
    return worker


__all__ = [
    "ImportTaskDTO",
    "PersistentImportWorker",
    "start_persistent_import_worker",
]
