"""Lifecycle boundary for restartable background facet index maintenance."""

from __future__ import annotations

import logging
from threading import Event, Thread

from sqlalchemy.orm import Session, sessionmaker

from app.modules.library.application.facet_index import RebuildFacetIndexBatch
from app.modules.library.infrastructure.uow import (
    SqlAlchemyFacetIndexUnitOfWork,
)

LOGGER = logging.getLogger(__name__)


class FacetIndexMaintenanceWorker:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        batch_size: int = 200,
        poll_seconds: float = 15.0,
    ) -> None:
        self._batch_size = batch_size
        self._poll_seconds = poll_seconds
        self._stop_event = Event()
        self._thread: Thread | None = None
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

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._rebuild.execute(limit=self._batch_size)
                if result.processed:
                    LOGGER.info(
                        "library_facet_index_batch outcome=success processed=%s may_have_more=%s",
                        result.processed,
                        result.may_have_more,
                    )
                if result.may_have_more:
                    continue
            except Exception:
                LOGGER.exception("library_facet_index_batch outcome=failed")
            self._stop_event.wait(self._poll_seconds)


def start_facet_index_maintenance_worker(
    session_factory: sessionmaker[Session],
) -> FacetIndexMaintenanceWorker:
    worker = FacetIndexMaintenanceWorker(session_factory)
    worker.start()
    return worker
