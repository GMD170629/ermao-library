"""Lifecycle boundary for restartable background facet index maintenance."""

from __future__ import annotations

import logging
from threading import Event, Thread
from time import monotonic

from sqlalchemy.orm import Session, sessionmaker

from app.core.database_errors import is_database_busy_error
from app.modules.library.application.facet_index import RebuildFacetIndexBatch
from app.modules.library.infrastructure.uow import (
    SqlAlchemyFacetIndexUnitOfWork,
)

LOGGER = logging.getLogger(__name__)
FACET_INDEX_BATCH_SIZE = 25
FACET_INDEX_BATCH_YIELD_SECONDS = 0.1
FACET_INDEX_BUSY_RETRY_SECONDS = 1.0
FACET_INDEX_IDLE_POLL_SECONDS = 15.0
FACET_INDEX_BUSY_LOG_INTERVAL_SECONDS = 30.0


class FacetIndexMaintenanceWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        batch_size: int = FACET_INDEX_BATCH_SIZE,
        batch_yield_seconds: float = FACET_INDEX_BATCH_YIELD_SECONDS,
        busy_retry_seconds: float = FACET_INDEX_BUSY_RETRY_SECONDS,
        poll_seconds: float = FACET_INDEX_IDLE_POLL_SECONDS,
    ) -> None:
        self._batch_size = batch_size
        self._batch_yield_seconds = batch_yield_seconds
        self._busy_retry_seconds = busy_retry_seconds
        self._poll_seconds = poll_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._last_busy_log_at: float | None = None
        self._rebuild = RebuildFacetIndexBatch(
            lambda: SqlAlchemyFacetIndexUnitOfWork(session_factory)
        )

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._run,
            name="library-facet-index-maintenance",
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
            result = self._rebuild.execute(limit=self._batch_size)
        except Exception as error:  # noqa: BLE001 — worker containment boundary
            if is_database_busy_error(error):
                now = monotonic()
                if (
                    self._last_busy_log_at is None
                    or now - self._last_busy_log_at
                    >= FACET_INDEX_BUSY_LOG_INTERVAL_SECONDS
                ):
                    LOGGER.warning(
                        "library_facet_index_batch outcome=deferred reason=database_busy retry_seconds=%s",
                        self._busy_retry_seconds,
                    )
                    self._last_busy_log_at = now
                return self._busy_retry_seconds
            LOGGER.exception("library_facet_index_batch outcome=failed")
            return self._poll_seconds
        if result.processed:
            duration_ms = round((monotonic() - started_at) * 1000)
            LOGGER.info(
                "library_facet_index_batch outcome=success processed=%s may_have_more=%s duration_ms=%s",
                result.processed,
                result.may_have_more,
                duration_ms,
            )
        if result.processed or result.may_have_more:
            return self._batch_yield_seconds
        return self._poll_seconds

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self._process_once())


def start_facet_index_maintenance_worker(
    session_factory: sessionmaker[Session],
) -> FacetIndexMaintenanceWorker:
    worker = FacetIndexMaintenanceWorker(session_factory)
    worker.start()
    return worker
