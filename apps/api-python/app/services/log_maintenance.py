from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.bootstrap.auth import delete_expired_or_disabled_sessions
from app.bootstrap.system import maintain_system_events
from app.core.auth import utcnow
from app.core.database_errors import is_database_busy_error

LOGGER = logging.getLogger(__name__)


class SystemEventMaintenanceWorker:
    def __init__(
        self, db_factory: Callable[[], Session], interval_seconds: int = 15 * 60
    ) -> None:
        self._db_factory = db_factory
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="system-event-maintenance", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

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
        while not self._stop.wait(self._interval_seconds):
            try:
                self.run_once()
            except Exception as exc:
                if is_database_busy_error(exc):
                    LOGGER.info(
                        "system maintenance outcome=deferred reason=database_busy"
                    )
                else:
                    LOGGER.exception("system maintenance iteration failed")
