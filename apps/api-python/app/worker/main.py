from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import SessionLocal, engine
from app.services.metadata_lookup_queue import MetadataLookupWorker
from app.services.organize_scheduler import OrganizerScheduler
from app.worker.watcher import WorkerManager
from app.worker.persistent_import_queue import start_persistent_import_worker
from app.services.queue_runtime import active_restart_operation, update_restart_operation
from app.services.system_events import record_system_event

READY_FILE = Path(os.environ.get("SCAN_WORKER_READY_FILE") or "/tmp/scan-worker-ready")


def startup_check() -> None:
    settings = get_settings()
    monitor_root = settings.resolved_monitor_root
    if monitor_root is None or not monitor_root.is_dir():
        raise RuntimeError(f"[import-worker] MONITOR_ROOT is not a directory: {monitor_root}")
    if not os.access(monitor_root, os.R_OK):
        raise RuntimeError(f"[import-worker] MONITOR_ROOT is not readable: {monitor_root}")


def main() -> None:
    startup_check()
    settings = get_settings()
    bootstrap_database(engine, settings)
    manager = WorkerManager(SessionLocal, settings)
    persistent_import_worker = start_persistent_import_worker(SessionLocal, settings)
    metadata_worker = MetadataLookupWorker(SessionLocal, settings)
    organizer_scheduler = OrganizerScheduler(SessionLocal)
    stopping = False
    stop_event = threading.Event()

    def shutdown(signum: int, _frame) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        print(f"[import-worker] signal {signum} received, closing watchers", flush=True)
        READY_FILE.unlink(missing_ok=True)
        manager.shutdown()
        persistent_import_worker.stop()
        metadata_worker.shutdown()
        organizer_scheduler.shutdown()
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    manager.refresh_worker_state()
    metadata_worker.start()
    organizer_scheduler.start()
    READY_FILE.write_text(str(os.getpid()), encoding="utf-8")
    print("[import-worker] ready", flush=True)

    refresh_interval = int(os.environ.get("MONITOR_REFRESH_INTERVAL_MS") or "30000") / 1000
    next_refresh = time.monotonic() + refresh_interval
    restart_operation_id: str | None = None
    while not stop_event.wait(1):
        if time.monotonic() >= next_refresh:
            manager.refresh_worker_state()
            next_refresh = time.monotonic() + refresh_interval
        try:
            with SessionLocal() as db:
                operation = active_restart_operation(db)
                if operation and restart_operation_id is None:
                    restart_operation_id = str(operation["id"])
                    persistent_import_worker.request_stop()
                    update_restart_operation(db, restart_operation_id, "waiting", "queue.restart.waiting")
                if restart_operation_id and not persistent_import_worker.is_alive():
                    update_restart_operation(db, restart_operation_id, "running", "queue.restart.starting")
                    persistent_import_worker = start_persistent_import_worker(SessionLocal, settings)
                    update_restart_operation(db, restart_operation_id, "completed", "queue.restart.completed")
                    record_system_event(
                        db,
                        source="system",
                        action="queue.restarted",
                        message="导入队列已安全重启",
                        level="warning",
                        actor_type="admin",
                        actor_id=str((operation or {}).get("actorUserId") or ""),
                        target_type="queue",
                        target_id="import",
                        metadata={"operationId": restart_operation_id},
                        commit=True,
                    )
                    restart_operation_id = None
        except Exception as exc:
            if restart_operation_id:
                try:
                    with SessionLocal() as db:
                        update_restart_operation(db, restart_operation_id, "failed", "queue.restart.failed")
                finally:
                    restart_operation_id = None
            print(f"[import-worker] queue restart control failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
