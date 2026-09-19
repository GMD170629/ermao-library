from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.bootstrap.auth import delete_expired_or_disabled_sessions
from app.bootstrap.system import maintain_system_events
from app.core.auth import utcnow
from app.core.config import Settings
from app.core.database_errors import is_database_busy_error
from app.core.exception_diagnostics import record_exception
from app.services.default_cover_cleanup import cleanup_default_cover_residue
from app.services.health_runs import fail_abandoned_health_runs

LOGGER = logging.getLogger(__name__)


class SystemEventMaintenanceWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        interval_seconds: int = 15 * 60,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._interval_seconds = interval_seconds
        self._settings = settings
        self._startup_pending = {"health", "covers"} if settings is not None else set()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="system-event-maintenance", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def request_stop(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self.request_stop()
        if self._thread.is_alive():
            self._thread.join()

    def _recover_startup_maintenance(self) -> None:
        for name in tuple(self._startup_pending):
            if self._stop.is_set():
                return
            try:
                with self._db_factory() as db:
                    if name == "health":
                        fail_abandoned_health_runs(db)
                    elif self._settings is not None:
                        cleanup_default_cover_residue(db, self._settings)
            except Exception as error:  # noqa: BLE001 - independent deferred maintenance.
                record_exception(
                    LOGGER,
                    "startup.maintenance_deferred",
                    error,
                    context={"stage": name, "outcome": "deferred"},
                    source="system",
                    action="startup.maintenance_deferred",
                )
            else:
                self._startup_pending.remove(name)

    def run_once(self) -> dict[str, int]:
        with self._db_factory() as db:
            current_time = utcnow()
            expired_sessions_deleted = delete_expired_or_disabled_sessions(
                db,
                current_time=current_time,
            )
            result = maintain_system_events(db)
            return {
                **result,
                "expiredSessionsDeleted": expired_sessions_deleted,
            }

    def _run(self) -> None:
        self._recover_startup_maintenance()
        while not self._stop.wait(self._interval_seconds):
            self._recover_startup_maintenance()
            try:
                self.run_once()
            except Exception as exc:
                if is_database_busy_error(exc):
                    LOGGER.info(
                        "system maintenance outcome=deferred reason=database_busy"
                    )
                else:
                    LOGGER.exception("system maintenance iteration failed")
