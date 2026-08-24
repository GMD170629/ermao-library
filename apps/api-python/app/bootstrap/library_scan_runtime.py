"""Worker composition and lifecycle for library scan reconciliation."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.library import Library
from app.models.settings import SystemSetting
from app.modules.imports.application.readable_resource.ports import UnitOfWorkPort
from app.modules.imports.application.readable_resource.request_library_scan import (
    LibraryScanTrigger,
    RequestLibraryScan,
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.library_scan_schedule import (
    LIBRARY_SCAN_INTERVAL_MINUTES_KEY,
    LIBRARY_SCAN_WATCH_ENABLED_KEY,
    LibraryScanSettings,
    next_periodic_scan_at,
)
from app.modules.imports.infrastructure.library_scan_settings import (
    SqlAlchemyLibraryScanSettingsRepository,
)
from app.modules.imports.infrastructure.library_scan_watcher import (
    LibraryEventBuffer,
    LibraryScanWatcher,
    WatchedLibrary,
)

logger = logging.getLogger("ermao.library_scan")


class LibraryScanCoordinator:
    def __init__(
        self,
        *,
        session: Session,
        settings: Settings,
        request_scan: RequestLibraryScan,
        uow: UnitOfWorkPort,
        refresh_seconds: float = 5.0,
    ) -> None:
        self._session = session
        self._settings = settings
        self._request_scan = request_scan
        self._uow = uow
        self._refresh_seconds = refresh_seconds
        self._buffer = LibraryEventBuffer(quiet_seconds=5.0)
        self._watcher = LibraryScanWatcher(self._buffer)
        self._libraries: tuple[WatchedLibrary, ...] = ()
        self._settings_token: tuple[tuple[str, str, datetime], ...] = ()
        self._next_refresh_at = 0.0
        self._next_periodic_at: datetime | None = None
        self._started = False
        self._startup_pending: set[str] = set()

    def tick(self) -> None:
        monotonic_now = time.monotonic()
        now = datetime.now(UTC)
        if monotonic_now >= self._next_refresh_at:
            self._refresh(now)
            self._next_refresh_at = monotonic_now + self._refresh_seconds

        for library_id in tuple(self._startup_pending):
            if self._request(library_id, "STARTUP"):
                self._startup_pending.discard(library_id)

        for library_id in self._buffer.ready(observed_at=monotonic_now):
            if self._request(library_id, "WATCHER"):
                self._buffer.acknowledge(library_id)

        if self._next_periodic_at is not None and now >= self._next_periodic_at:
            completed = True
            for library in self._libraries:
                completed = self._request(library.library_id, "PERIODIC") and completed
            if completed:
                scan_settings = self._load_settings()
                self._next_periodic_at = next_periodic_scan_at(
                    now, scan_settings.interval_minutes
                )

    def shutdown(self) -> None:
        self._watcher.shutdown()

    def _refresh(self, now: datetime) -> None:
        libraries = tuple(
            WatchedLibrary(library_id, Path(root_path).expanduser().resolve())
            for library_id, root_path in self._session.execute(
                select(Library.id, Library.root_path)
                .where(Library.enabled.is_(True))
                .order_by(Library.id.asc())
            ).all()
        )
        token = tuple(
            (key, value, updated_at)
            for key, value, updated_at in self._session.execute(
                select(SystemSetting.key, SystemSetting.value, SystemSetting.updated_at)
                .where(
                    SystemSetting.key.in_(
                        (
                            LIBRARY_SCAN_WATCH_ENABLED_KEY,
                            LIBRARY_SCAN_INTERVAL_MINUTES_KEY,
                        )
                    )
                )
                .order_by(SystemSetting.key.asc())
            ).all()
        )
        scan_settings = self._load_settings()
        self._uow.release_before_io()

        libraries_changed = libraries != self._libraries
        settings_changed = token != self._settings_token
        self._libraries = libraries
        self._buffer.retain({library.library_id for library in libraries})
        self._settings_token = token
        if settings_changed or self._next_periodic_at is None:
            self._next_periodic_at = next_periodic_scan_at(
                now, scan_settings.interval_minutes
            )

        try:
            rebuilt = self._watcher.reconcile(
                libraries,
                enabled=scan_settings.watch_enabled,
            )
        except (OSError, RuntimeError):
            rebuilt = False
            logger.warning(
                "library_scan.watcher_unavailable",
                extra={"library_count": len(libraries)},
                exc_info=True,
            )
        if not self._started or libraries_changed or rebuilt:
            for library in libraries:
                if not self._request(library.library_id, "STARTUP"):
                    self._startup_pending.add(library.library_id)
        enabled_ids = {library.library_id for library in libraries}
        self._startup_pending.intersection_update(enabled_ids)
        self._started = True

    def _load_settings(self) -> LibraryScanSettings:
        return SqlAlchemyLibraryScanSettingsRepository(
            self._session,
            legacy_interval_ms=self._settings.library_scan_interval_ms,
        ).load()

    def _request(self, library_id: str, trigger: LibraryScanTrigger) -> bool:
        try:
            self._request_scan.execute(
                RequestLibraryScanCommand(library_id=library_id, trigger=trigger)
            )
        except (OSError, RuntimeError, SQLAlchemyError):
            self._uow.recover_after_failure()
            logger.warning(
                "library_scan.request_deferred",
                extra={"library_id": library_id, "trigger": trigger},
                exc_info=True,
            )
            return False
        return True


__all__ = ["LibraryScanCoordinator"]
