from __future__ import annotations

import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.services.system_events import prune_system_events


class SystemEventMaintenanceWorker:
    def __init__(self, db_factory: Callable[[], Session], interval_seconds: int = 15 * 60) -> None:
        self._db_factory = db_factory
        self._interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="system-event-maintenance", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                with self._db_factory() as db:
                    prune_system_events(db, commit=True)
            except Exception:
                # Maintenance must never take the API process down.
                continue

