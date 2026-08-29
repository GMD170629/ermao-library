"""Process boundary for the single-consumer readable-resource worker."""

from __future__ import annotations

import logging
import os
import signal
import threading
from pathlib import Path
from tempfile import gettempdir

from app.bootstrap.library_scan_runtime import (
    LibraryScanCoordinator,
)
from app.bootstrap.metadata import build_automatic_metadata_request_gate
from app.bootstrap.prestart import verify_current_schema
from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.core.config import get_settings
from app.db.session import (
    BackgroundSessionLocal,
    HeartbeatSessionLocal,
    MetadataMaintenanceSessionLocal,
    engine,
)

logger = logging.getLogger("ermao.import_worker")


def worker_ready_file() -> Path:
    """Return the configured probe path or a platform-native temporary path."""

    configured = os.environ.get("IMPORT_WORKER_READY_FILE")
    if configured:
        return Path(configured)
    return Path(gettempdir()) / "import-worker-ready"


def main() -> None:
    from app.services.metadata_lookup_queue import MetadataLookupWorker
    from app.services.organize_scheduler import OrganizerScheduler

    settings = get_settings()
    ready_file = worker_ready_file()
    verify_current_schema(engine)

    import_session = BackgroundSessionLocal()
    pipeline = build_readable_resource_pipeline(import_session)
    readable_worker = build_readable_resource_worker(pipeline)
    readable_worker.startup()
    if pipeline.request_library_scan is None:
        raise RuntimeError("library scan requester is not configured")
    scan_coordinator = LibraryScanCoordinator(
        session=import_session,
        settings=settings,
        request_scan=pipeline.request_library_scan,
        uow=pipeline.uow,
    )

    metadata_worker = MetadataLookupWorker(
        MetadataMaintenanceSessionLocal,
        settings,
        heartbeat_db_factory=HeartbeatSessionLocal,
        automatic_request_gate=build_automatic_metadata_request_gate(),
    )
    organizer_scheduler = OrganizerScheduler(BackgroundSessionLocal)
    stop_event = threading.Event()
    stopping = False

    def shutdown(signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logger.info("readable_resource.worker.stopping", extra={"signal": signum})
        ready_file.unlink(missing_ok=True)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    metadata_worker.start()
    organizer_scheduler.start()
    ready_file.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("readable_resource.worker.ready")

    try:
        while not stop_event.is_set():
            try:
                scan_coordinator.tick()
                outcome = readable_worker.process_once()
            except Exception:
                # This is the process-level containment boundary.  Task-level
                # failures are contained and persisted by the target worker.
                readable_worker.recover_after_loop_failure()
                logger.exception("readable_resource.worker.loop_failure")
                outcome = "error"
            if outcome == "idle":
                stop_event.wait(settings.import_queue_interval_seconds)
    finally:
        ready_file.unlink(missing_ok=True)
        metadata_worker.shutdown()
        organizer_scheduler.shutdown()
        scan_coordinator.shutdown()
        import_session.close()


if __name__ == "__main__":
    main()
