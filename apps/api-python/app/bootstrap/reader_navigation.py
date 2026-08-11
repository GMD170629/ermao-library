"""Lifecycle boundary for bounded historical EPUB navigation maintenance."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.database_errors import (
    is_database_busy_error,
    is_database_operation_timeout,
)
from app.modules.reader.application.navigation_maintenance import (
    RebuildEpubNavigationBatch,
)
from app.modules.reader.infrastructure.epub_navigation_recovery import (
    FileReaderEpubNavigationParser,
)
from app.modules.reader.infrastructure.navigation_maintenance import (
    prepare_epub_navigation_write,
)
from app.modules.reader.infrastructure.uow import (
    SqlAlchemyEpubNavigationMaintenanceUnitOfWork,
)

LOGGER = logging.getLogger(__name__)
READER_NAVIGATION_BATCH_SIZE = 25
READER_NAVIGATION_BATCH_YIELD_SECONDS = 0.1
READER_NAVIGATION_BUSY_RETRY_SECONDS = 1.0
READER_NAVIGATION_IDLE_POLL_SECONDS = 15.0
READER_NAVIGATION_BUSY_LOG_INTERVAL_SECONDS = 30.0


class ReaderNavigationMaintenanceWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        *,
        batch_size: int = READER_NAVIGATION_BATCH_SIZE,
        batch_yield_seconds: float = READER_NAVIGATION_BATCH_YIELD_SECONDS,
        busy_retry_seconds: float = READER_NAVIGATION_BUSY_RETRY_SECONDS,
        poll_seconds: float = READER_NAVIGATION_IDLE_POLL_SECONDS,
    ) -> None:
        self._batch_size = batch_size
        self._batch_yield_seconds = batch_yield_seconds
        self._busy_retry_seconds = busy_retry_seconds
        self._poll_seconds = poll_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._last_busy_log_at: float | None = None
        self._cursor: str | None = None
        self._rebuild = RebuildEpubNavigationBatch(
            lambda: SqlAlchemyEpubNavigationMaintenanceUnitOfWork(session_factory),
            FileReaderEpubNavigationParser(settings.resolved_storage_root),
            lambda: datetime.now(UTC),
            prepare_epub_navigation_write,
        )

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._run,
            name="reader-navigation-maintenance",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _process_once(self) -> float:
        started_at = monotonic()
        try:
            result = self._rebuild.execute(
                limit=self._batch_size,
                after_volume_id=self._cursor,
            )
        except Exception as error:  # Worker containment boundary records retry policy.
            deferred_reason = (
                "database_busy"
                if is_database_busy_error(error)
                else "time_budget_exceeded"
                if is_database_operation_timeout(error)
                else None
            )
            if deferred_reason is not None:
                now = monotonic()
                if (
                    self._last_busy_log_at is None
                    or now - self._last_busy_log_at
                    >= READER_NAVIGATION_BUSY_LOG_INTERVAL_SECONDS
                ):
                    LOGGER.warning(
                        "reader_navigation_batch outcome=deferred reason=%s retry_seconds=%s",
                        deferred_reason,
                        self._busy_retry_seconds,
                    )
                    self._last_busy_log_at = now
                return self._busy_retry_seconds
            LOGGER.exception("reader_navigation_batch outcome=failed")
            return self._poll_seconds

        if not result.scanned:
            if self._cursor is not None:
                self._cursor = None
                return self._batch_yield_seconds
            return self._poll_seconds
        self._cursor = result.last_volume_id
        LOGGER.info(
            "reader_navigation_batch outcome=success scanned=%s processed=%s parse_failures=%s duration_ms=%s",
            result.scanned,
            result.processed,
            result.parse_failures,
            round((monotonic() - started_at) * 1000),
        )
        return self._batch_yield_seconds

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._process_once())


def start_reader_navigation_maintenance_worker(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> ReaderNavigationMaintenanceWorker:
    worker = ReaderNavigationMaintenanceWorker(session_factory, settings)
    worker.start()
    return worker


__all__ = [
    "ReaderNavigationMaintenanceWorker",
    "start_reader_navigation_maintenance_worker",
]
