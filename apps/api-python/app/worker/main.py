from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

from app.bootstrap.metadata import build_automatic_metadata_request_gate
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.session import HeartbeatSessionLocal, SessionLocal, engine
from app.services.metadata_lookup_queue import MetadataLookupWorker
from app.services.organize_scheduler import OrganizerScheduler
from app.services.queue_runtime import (
    active_queue_operation,
    update_queue_operation,
)
from app.services.system_events import record_system_event
from app.worker.persistent_import_queue import start_persistent_import_worker
from app.worker.watcher import WorkerManager

READY_FILE = Path(os.environ.get("SCAN_WORKER_READY_FILE") or "/tmp/scan-worker-ready")


def main() -> None:
    settings = get_settings()
    bootstrap_database(engine, settings)
    manager = WorkerManager(SessionLocal, settings)
    persistent_import_worker = start_persistent_import_worker(
        SessionLocal,
        settings,
        HeartbeatSessionLocal,
    )
    metadata_worker = MetadataLookupWorker(
        SessionLocal,
        settings,
        heartbeat_db_factory=HeartbeatSessionLocal,
        automatic_request_gate=build_automatic_metadata_request_gate(),
    )
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

    refresh_interval = (
        int(os.environ.get("MONITOR_REFRESH_INTERVAL_MS") or "30000") / 1000
    )
    next_refresh = time.monotonic() + refresh_interval
    queue_operation_id: str | None = None
    queue_operation_action: str | None = None
    queue_operation_actor_id: str | None = None
    import_scheduling_paused = False
    while not stop_event.wait(1):
        if time.monotonic() >= next_refresh:
            manager.refresh_worker_state()
            next_refresh = time.monotonic() + refresh_interval
        try:
            with SessionLocal() as db:
                operation = active_queue_operation(db)
                if operation and queue_operation_id is None:
                    queue_operation_id = str(operation["id"])
                    queue_operation_action = str(operation["action"])
                    queue_operation_actor_id = str(operation.get("actorUserId") or "")
                    persistent_import_worker.request_stop()
                    update_queue_operation(
                        db,
                        queue_operation_id,
                        "waiting",
                        f"queue.{queue_operation_action}.waiting",
                    )
                    if queue_operation_action == "clear":
                        import_scheduling_paused = True
                        manager.pause_import_scheduling()
                if queue_operation_id and not persistent_import_worker.is_alive():
                    action = queue_operation_action or "restart"
                    update_queue_operation(
                        db,
                        queue_operation_id,
                        "running",
                        f"queue.{action}.running",
                    )
                    deleted = (
                        persistent_import_worker.clear_records()
                        if action == "clear"
                        else None
                    )
                    persistent_import_worker = start_persistent_import_worker(
                        SessionLocal,
                        settings,
                        HeartbeatSessionLocal,
                    )
                    if import_scheduling_paused:
                        manager.resume_import_scheduling()
                        import_scheduling_paused = False
                    try:
                        record_system_event(
                            db,
                            source="system",
                            action=(
                                "queue.cleared"
                                if action == "clear"
                                else "queue.restarted"
                            ),
                            message=(
                                f"导入队列已安全清理，共删除 {deleted or 0} 条记录"
                                if action == "clear"
                                else "导入队列已安全重启"
                            ),
                            level="warning",
                            actor_type="admin",
                            actor_id=queue_operation_actor_id,
                            target_type="queue",
                            target_id="import",
                            metadata={
                                "operationId": queue_operation_id,
                                "action": action,
                                "deleted": deleted,
                            },
                            commit=True,
                        )
                    except Exception as event_error:
                        print(
                            "[import-worker] queue control event write failed: "
                            f"{event_error}",
                            flush=True,
                        )
                    update_queue_operation(
                        db,
                        queue_operation_id,
                        "completed",
                        f"queue.{action}.completed",
                    )
                    queue_operation_id = None
                    queue_operation_action = None
                    queue_operation_actor_id = None
        except Exception as exc:
            failed_operation_id = queue_operation_id
            failed_action = queue_operation_action or "restart"
            if failed_operation_id:
                try:
                    if not persistent_import_worker.is_alive():
                        persistent_import_worker = start_persistent_import_worker(
                            SessionLocal,
                            settings,
                            HeartbeatSessionLocal,
                        )
                    if import_scheduling_paused:
                        manager.resume_import_scheduling()
                        import_scheduling_paused = False
                    with SessionLocal() as db:
                        update_queue_operation(
                            db,
                            failed_operation_id,
                            "failed",
                            f"queue.{failed_action}.failed",
                        )
                finally:
                    queue_operation_id = None
                    queue_operation_action = None
                    queue_operation_actor_id = None
            print(f"[import-worker] queue control failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
