from __future__ import annotations

import os
import signal
import threading
from pathlib import Path

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import SessionLocal, engine
from app.services.metadata_lookup_queue import MetadataLookupWorker
from app.services.organize_scheduler import OrganizerScheduler
from app.worker.watcher import WorkerManager
from app.worker.persistent_import_queue import start_persistent_import_worker

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
    while not stop_event.wait(refresh_interval):
        manager.refresh_worker_state()


if __name__ == "__main__":
    main()
