from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Sequence
from typing import cast

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.library_facet_index import FacetIndexMaintenanceWorker
from app.modules.library.application.facet_index import (
    FacetIndexBatchResult,
    RebuildFacetIndexBatch,
)


class StubRebuild:
    def __init__(
        self,
        outcomes: Sequence[FacetIndexBatchResult | BaseException],
    ) -> None:
        self._outcomes = iter(outcomes)
        self.limits: list[int] = []
        self.called = threading.Event()

    def execute(self, *, limit: int = 200) -> FacetIndexBatchResult:
        self.limits.append(limit)
        self.called.set()
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _worker(stub: StubRebuild) -> FacetIndexMaintenanceWorker:
    worker = FacetIndexMaintenanceWorker(sessionmaker[Session]())
    worker._rebuild = cast(RebuildFacetIndexBatch, stub)
    return worker


def test_facet_index_worker_yields_between_batches_and_polls_when_idle() -> None:
    stub = StubRebuild(
        (
            FacetIndexBatchResult(processed=25, may_have_more=True),
            FacetIndexBatchResult(processed=3, may_have_more=False),
            FacetIndexBatchResult(processed=0, may_have_more=False),
        )
    )
    worker = _worker(stub)

    assert worker._process_once() == 0.1
    assert worker._process_once() == 0.1
    assert worker._process_once() == 15.0
    assert stub.limits == [25, 25, 25]


def test_facet_index_worker_defers_and_throttles_database_busy_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    busy = OperationalError(
        "UPDATE LibraryWork",
        {},
        sqlite3.OperationalError("database is locked"),
    )
    stub = StubRebuild((busy, busy))
    worker = _worker(stub)

    with caplog.at_level(logging.WARNING):
        assert worker._process_once() == 1.0
        assert worker._process_once() == 1.0

    messages = [
        record.getMessage()
        for record in caplog.records
        if "outcome=deferred reason=database_busy" in record.getMessage()
    ]
    assert len(messages) == 1
    assert all(record.exc_info is None for record in caplog.records)


def test_facet_index_worker_stop_interrupts_idle_wait() -> None:
    stub = StubRebuild((FacetIndexBatchResult(processed=0, may_have_more=False),))
    worker = _worker(stub)

    worker.start()
    assert stub.called.wait(timeout=1)
    worker.stop()

    assert worker._thread is None
