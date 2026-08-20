from __future__ import annotations

import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError

from app.bootstrap.imports import persist_import_queue_operation_checkpoint
from app.bootstrap.metadata import build_automatic_metadata_request_gate
from app.bootstrap.prestart import verify_current_schema
from app.core.config import get_settings
from app.db.session import (
    BackgroundSessionLocal,
    HeartbeatSessionLocal,
    MetadataMaintenanceSessionLocal,
    engine,
)
from app.modules.imports.application.queue_control import (
    PreparedImportQueueOperationCheckpoint,
)
from app.modules.system.public import PreparedSystemEvent, is_database_busy_error
from app.services.metadata_lookup_queue import MetadataLookupWorker
from app.services.organize_scheduler import OrganizerScheduler
from app.services.queue_runtime import (
    active_queue_operation,
)
from app.services.system_events import (
    prepare_system_event,
)
from app.worker.persistent_import_queue import start_persistent_import_worker
from app.worker.watcher import WorkerManager

READY_FILE = Path(os.environ.get("SCAN_WORKER_READY_FILE") or "/tmp/scan-worker-ready")


@dataclass(frozen=True, slots=True)
class QueueOperationProjection:
    id: str
    action: str
    actor_user_id: str | None


def _load_active_queue_operation() -> QueueOperationProjection | None:
    with BackgroundSessionLocal() as db:
        row = active_queue_operation(db)
    if row is None:
        return None
    return QueueOperationProjection(
        id=str(row["id"]),
        action=str(row["action"]),
        actor_user_id=str(row.get("actorUserId") or "") or None,
    )


def _persist_queue_operation_status(
    operation_id: str,
    status: str,
    message_code: str,
    events: tuple[PreparedSystemEvent, ...] = (),
) -> None:
    checkpoint = PreparedImportQueueOperationCheckpoint(
        operation_id=operation_id,
        status=status,
        message_code=message_code,
        checkpoint_at=datetime.now(UTC),
        events=events,
    )
    with BackgroundSessionLocal() as db:
        persist_import_queue_operation_checkpoint(db, checkpoint)


def main() -> None:
    settings = get_settings()
    verify_current_schema(engine)
    manager = WorkerManager(BackgroundSessionLocal, settings)
    persistent_import_worker = start_persistent_import_worker(
        BackgroundSessionLocal,
        settings,
        HeartbeatSessionLocal,
    )
    metadata_worker = MetadataLookupWorker(
        MetadataMaintenanceSessionLocal,
        settings,
        heartbeat_db_factory=HeartbeatSessionLocal,
        automatic_request_gate=build_automatic_metadata_request_gate(),
    )
    organizer_scheduler = OrganizerScheduler(BackgroundSessionLocal)
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
            operation = _load_active_queue_operation()
            if operation and queue_operation_id is None:
                queue_operation_id = operation.id
                queue_operation_action = operation.action
                queue_operation_actor_id = operation.actor_user_id
                persistent_import_worker.request_stop()
                _persist_queue_operation_status(
                    queue_operation_id,
                    "waiting",
                    f"queue.{queue_operation_action}.waiting",
                )
                if queue_operation_action == "clear":
                    import_scheduling_paused = True
                    manager.pause_import_scheduling()
            if queue_operation_id and not persistent_import_worker.is_alive():
                action = queue_operation_action or "restart"
                _persist_queue_operation_status(
                    queue_operation_id,
                    "running",
                    f"queue.{action}.running",
                )
                deleted = (
                    persistent_import_worker.clear_records()
                    if action == "clear"
                    else None
                )
                prepared_event = prepare_system_event(
                    source="system",
                    action=(
                        "queue.cleared" if action == "clear" else "queue.restarted"
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
                )
                try:
                    _persist_queue_operation_status(
                        queue_operation_id,
                        "completed",
                        f"queue.{action}.completed",
                        (prepared_event,),
                    )
                except OperationalError as checkpoint_error:
                    if not is_database_busy_error(checkpoint_error):
                        raise
                    print(
                        "[import-worker] queue completion deferred "
                        "reason=database_busy",
                        flush=True,
                    )
                    continue
                persistent_import_worker = start_persistent_import_worker(
                    BackgroundSessionLocal,
                    settings,
                    HeartbeatSessionLocal,
                )
                if import_scheduling_paused:
                    manager.resume_import_scheduling()
                    import_scheduling_paused = False
                queue_operation_id = None
                queue_operation_action = None
                queue_operation_actor_id = None
        # Worker loop is the process containment boundary and must persist an
        # explicit terminal checkpoint for every unexpected task failure.
        except Exception as exc:  # noqa: BLE001
            failed_operation_id = queue_operation_id
            failed_action = queue_operation_action or "restart"
            if failed_operation_id:
                try:
                    if not persistent_import_worker.is_alive():
                        persistent_import_worker = start_persistent_import_worker(
                            BackgroundSessionLocal,
                            settings,
                            HeartbeatSessionLocal,
                        )
                    if import_scheduling_paused:
                        manager.resume_import_scheduling()
                        import_scheduling_paused = False
                    failed_event = prepare_system_event(
                        source="system",
                        action="queue.control.failed",
                        message="IMPORT_QUEUE_CONTROL_FAILED",
                        level="error",
                        actor_type="admin",
                        actor_id=queue_operation_actor_id,
                        target_type="queue",
                        target_id="import",
                        metadata={
                            "operationId": failed_operation_id,
                            "action": failed_action,
                            "errorType": type(exc).__name__,
                        },
                    )
                    _persist_queue_operation_status(
                        failed_operation_id,
                        "failed",
                        f"queue.{failed_action}.failed",
                        (failed_event,),
                    )
                finally:
                    queue_operation_id = None
                    queue_operation_action = None
                    queue_operation_actor_id = None
            print(f"[import-worker] queue control failed: {exc}", flush=True)


if __name__ == "__main__":
    main()
