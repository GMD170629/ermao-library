"""Process boundary for the single-consumer readable-resource worker."""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from collections.abc import Callable
from pathlib import Path
from tempfile import gettempdir
from time import monotonic

from app.bootstrap.file_moves import build_file_move_worker
from app.bootstrap.library_scan_runtime import (
    LibraryScanCoordinator,
)
from app.bootstrap.metadata import build_automatic_metadata_request_gate
from app.bootstrap.prestart import verify_current_schema
from app.bootstrap.readable_resource_pipeline import (
    build_readable_resource_pipeline,
    build_readable_resource_worker,
)
from app.bootstrap.standard_writeback import (
    maintain_standard_writeback,
    process_standard_writeback,
    recover_standard_writeback,
)
from app.core.config import get_settings
from app.core.database_errors import is_database_busy_error
from app.core.exception_diagnostics import (
    configure_exception_storage,
    install_exception_hooks,
    record_exception,
)
from app.core.logging_config import configure_logging
from app.db.session import (
    BackgroundSessionLocal,
    HeartbeatSessionLocal,
    MetadataMaintenanceSessionLocal,
    engine,
)
from app.services.queue_runtime import QueueHeartbeatPump

logger = logging.getLogger("ermao.import_worker")


def _report_failure(stage: str, error: Exception) -> None:
    try:
        record_exception(
            logger,
            "worker.component_failure",
            error,
            context={"stage": stage, "outcome": "paused"},
            source="import",
            action="worker.component_failure",
        )
    except Exception as diagnostic_error:  # noqa: BLE001 - final safe output boundary.
        logger.error(
            "worker.component_failure stage=%s type=%s diagnostic_type=%s",
            stage,
            type(error).__name__,
            type(diagnostic_error).__name__,
        )


def _cleanup(stage: str, action: Callable[[], object]) -> bool:
    try:
        action()
        return True
    except Exception as error:  # noqa: BLE001 - release remaining independent resources.
        _report_failure(stage, error)
        return False


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
    configure_logging()
    configure_exception_storage(BackgroundSessionLocal)
    install_exception_hooks()
    verify_current_schema(engine)

    import_session = None
    file_move_session = None
    file_move_worker = None
    readable_worker = None
    scan_coordinator = None
    metadata_worker = None
    organizer_scheduler = None
    stop_event = threading.Event()
    import_heartbeat = QueueHeartbeatPump(
        HeartbeatSessionLocal,
        queue_name="import",
        instance_id=f"import-{os.getpid()}",
        poll_interval_seconds=settings.import_queue_interval_seconds,
    )
    stopping = False

    def shutdown(signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        logger.info("readable_resource.worker.stopping", extra={"signal": signum})
        stop_event.set()
        _cleanup("ready_remove", lambda: ready_file.unlink(missing_ok=True))
        for component in (scan_coordinator, metadata_worker, organizer_scheduler):
            if component is not None:
                _cleanup("request_stop", component.request_stop)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        import_heartbeat.start()
        import_heartbeat.pulse(status="recovering")
        try:
            metadata_worker = MetadataLookupWorker(
                MetadataMaintenanceSessionLocal,
                settings,
                heartbeat_db_factory=HeartbeatSessionLocal,
                automatic_request_gate=build_automatic_metadata_request_gate(),
                standard_handler=process_standard_writeback,
                standard_maintenance=maintain_standard_writeback,
                standard_recovery=recover_standard_writeback,
            )
            if not stop_event.is_set():
                metadata_worker.start()
        except Exception as error:  # noqa: BLE001 - optional component boundary.
            _report_failure("metadata_start", error)
            if metadata_worker is not None:
                _cleanup("metadata_stop", metadata_worker.shutdown)
        try:
            if not stop_event.is_set():
                organizer_scheduler = OrganizerScheduler(BackgroundSessionLocal)
                organizer_scheduler.start()
        except Exception as error:  # noqa: BLE001 - optional component boundary.
            _report_failure("organizer_start", error)
            if organizer_scheduler is not None:
                _cleanup("organizer_stop", organizer_scheduler.shutdown)
        if not stop_event.is_set():
            try:
                birth = Path(f"/proc/{os.getpid()}/stat")
                ready_file.write_text(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "startTime": birth.read_text().rsplit(")", 1)[1].split()[19]
                            if birth.exists()
                            else None,
                        }
                    ),
                    encoding="utf-8",
                )
            except OSError:
                logger.warning(
                    "WORKER_READY_WRITE_FAILED / 无法写入 Worker 就绪记录，继续运行"
                )
            logger.info("readable_resource.worker.ready")
        next_import_attempt = 0.0
        import_failures = 0
        scan_paused = False
        next_scan_attempt = 0.0
        imports_paused = False
        next_file_move_attempt = 0.0
        while not stop_event.is_set():
            if monotonic() >= next_file_move_attempt:
                try:
                    if file_move_worker is None:
                        file_move_session = BackgroundSessionLocal()
                        file_move_worker = build_file_move_worker(file_move_session)
                    file_move_worker.process_once()
                except Exception as error:  # noqa: BLE001 - contain one durable file task.
                    logger.warning(
                        "worker.file_move_failed type=%s", type(error).__name__
                    )
                    if file_move_session is not None:
                        _cleanup("file_move_rollback", file_move_session.rollback)
                    next_file_move_attempt = monotonic() + 60
            if imports_paused or monotonic() < next_import_attempt:
                stop_event.wait(settings.import_queue_interval_seconds)
                continue
            if readable_worker is None:
                try:
                    import_session = BackgroundSessionLocal()
                    pipeline = build_readable_resource_pipeline(import_session)
                    candidate = build_readable_resource_worker(pipeline)
                    candidate.startup()
                    readable_worker = candidate
                except Exception as error:  # noqa: BLE001 - recovery gates imports only.
                    _report_failure("import_recovery", error)
                    closed = import_session is None or _cleanup(
                        "import_close", import_session.close
                    )
                    import_failures += 1
                    imports_paused = not closed or not is_database_busy_error(error)
                    import_heartbeat.pulse(
                        status="paused" if imports_paused else "retrying",
                        error=f"recovery:{type(error).__name__}",
                    )
                    next_import_attempt = monotonic() + min(
                        300, 5 * 2 ** min(import_failures - 1, 6)
                    )
                    continue
                try:
                    if not stop_event.is_set():
                        scan_coordinator = LibraryScanCoordinator(
                            session=import_session,
                            settings=settings,
                            request_scan=pipeline.request_library_scan,
                            uow=pipeline.uow,
                        )
                except Exception as error:  # noqa: BLE001 - independent scan initialization.
                    _report_failure("scan_start", error)
                    scan_paused = True
                    imports_paused = not _cleanup(
                        "scan_rollback", readable_worker.recover_after_loop_failure
                    )
                    import_heartbeat.pulse(
                        status="paused" if imports_paused else "degraded",
                        error="scan-start-failed",
                    )
            if stop_event.is_set() or imports_paused:
                continue
            if (
                scan_coordinator is not None
                and not scan_paused
                and monotonic() >= next_scan_attempt
            ):
                try:
                    scan_coordinator.tick()
                except Exception as error:  # noqa: BLE001 - shared UoW must be recovered.
                    _report_failure("scan_tick", error)
                    scan_paused = not is_database_busy_error(error)
                    next_scan_attempt = monotonic() + 60
                    imports_paused = not _cleanup(
                        "scan_rollback", readable_worker.recover_after_loop_failure
                    )
                    import_heartbeat.pulse(
                        status="paused" if imports_paused else "degraded",
                        error="scan-tick-failed",
                    )
                    if scan_paused or imports_paused:
                        _cleanup("scan_request_stop", scan_coordinator.request_stop)
            if stop_event.is_set() or imports_paused:
                continue
            try:
                outcome = readable_worker.process_once()
                import_heartbeat.pulse(
                    status="degraded" if scan_paused else "running",
                    processed=outcome not in {"idle", "deferred"},
                )
            except Exception as error:  # noqa: BLE001 - process containment boundary
                _report_failure("import_loop", error)
                recovered = _cleanup(
                    "import_rollback", readable_worker.recover_after_loop_failure
                )
                # Keep the processor (including pending completion) and never
                # repeat startup recovery or unknown filesystem side effects.
                imports_paused = not recovered or not is_database_busy_error(error)
                import_heartbeat.pulse(
                    status="paused" if imports_paused else "retrying",
                    error=f"iteration:{type(error).__name__}",
                )
                if not imports_paused:
                    import_failures += 1
                    next_import_attempt = monotonic() + min(
                        300, 5 * 2 ** min(import_failures - 1, 6)
                    )
                outcome = "error"
            if outcome in {"idle", "error", "deferred"}:
                stop_event.wait(settings.import_queue_interval_seconds)
    finally:
        shutdown(0, None)
        _cleanup("import_heartbeat_stop", import_heartbeat.stop)
        for component in (metadata_worker, organizer_scheduler, scan_coordinator):
            if component is not None:
                _cleanup("component_shutdown", component.shutdown)
        if file_move_session is not None:
            _cleanup("file_move_close", file_move_session.close)
        if import_session is not None:
            _cleanup("import_close", import_session.close)


if __name__ == "__main__":
    main()
