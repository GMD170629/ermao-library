from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from time import monotonic

from sqlalchemy.orm import Session

from app.bootstrap.auth import delete_expired_or_disabled_sessions
from app.bootstrap.media import resource_preview_cache
from app.bootstrap.metadata import maintain_external_metadata_cache
from app.bootstrap.system import maintain_system_events
from app.core.auth import utcnow
from app.core.config import Settings
from app.core.exception_diagnostics import capture_exception, record_exception
from app.services.default_cover_cleanup import cleanup_default_cover_residue
from app.services.health_runs import fail_abandoned_health_runs

LOGGER = logging.getLogger(__name__)
CACHE_PRUNE_INTERVAL_SECONDS = 24 * 60 * 60


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
        self._preview_cache = (
            resource_preview_cache(settings)
            if settings is not None
            else None
        )
        self._next_preview_prune_at: float | None = None
        self._next_metadata_prune_at: float | None = None
        self._startup_pending: set[str] = set()
        if settings is not None:
            self._startup_pending.update({"health", "covers", "logs"})
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
                    elif name == "logs":
                        maintain_system_events(db)
                    elif self._settings is not None:
                        cleanup_default_cover_residue(db, self._settings)
            except Exception as error:  # noqa: BLE001 - independent deferred maintenance.
                capture_exception(error, persist=False)
                record_exception(
                    LOGGER,
                    "startup.maintenance_deferred",
                    error,
                    source="system",
                    action="startup.maintenance_deferred",
                )
            else:
                self._startup_pending.remove(name)

    def run_once(self) -> dict[str, int]:
        previews_deleted = self._prune_resource_previews()
        metadata_cache_deleted = self._prune_metadata_cache()
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
                "expiredResourcePreviewsDeleted": previews_deleted,
                "expiredMetadataCacheDeleted": metadata_cache_deleted,
            }

    def _prune_metadata_cache(self) -> int:
        now = monotonic()
        if self._next_metadata_prune_at is not None and now < self._next_metadata_prune_at:
            return 0
        self._next_metadata_prune_at = now + CACHE_PRUNE_INTERVAL_SECONDS
        try:
            with self._db_factory() as db:
                return maintain_external_metadata_cache(db, cancelled=self._stop.is_set)
        except Exception as error:  # noqa: BLE001 - independent optional maintenance.
            capture_exception(error, persist=False)
            record_exception(
                LOGGER,
                "metadata.cache_maintenance_failed",
                error,
                session_factory=self._db_factory,
            )
            return 0

    def _prune_resource_previews(self) -> int:
        if self._preview_cache is None:
            return 0
        now = monotonic()
        if self._next_preview_prune_at is not None and now < self._next_preview_prune_at:
            return 0
        self._next_preview_prune_at = now + CACHE_PRUNE_INTERVAL_SECONDS
        try:
            return self._preview_cache.prune(cancelled=self._stop.is_set)
        except Exception as error:  # noqa: BLE001 - optional maintenance boundary.
            capture_exception(error, persist=False)
            record_exception(
                LOGGER,
                "media.preview_cache.maintenance_failed",
                error,
                session_factory=self._db_factory,
            )
            return 0

    def _run(self) -> None:
        self._prune_resource_previews()
        self._prune_metadata_cache()
        self._recover_startup_maintenance()
        while not self._stop.wait(self._interval_seconds):
            self._recover_startup_maintenance()
            try:
                self.run_once()
            except Exception as exc:  # noqa: BLE001 - iteration boundary records every failed attempt
                capture_exception(exc, persist=False)
                record_exception(
                    LOGGER,
                    "system.maintenance_failed",
                    exc,
                    session_factory=self._db_factory,
                )
