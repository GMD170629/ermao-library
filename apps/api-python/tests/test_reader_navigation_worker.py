from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest
from app.bootstrap.reader_navigation import ReaderNavigationMaintenanceWorker
from app.core.config import Settings
from app.modules.reader.application.navigation_maintenance import (
    EpubNavigationBatchResult,
    RebuildEpubNavigationBatch,
)
from app.modules.reader.infrastructure.navigation_maintenance import (
    PreparedEpubNavigationWrite,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker


class StubRebuild:
    def __init__(
        self,
        outcomes: Sequence[EpubNavigationBatchResult | BaseException],
    ) -> None:
        self._outcomes = iter(outcomes)
        self.calls: list[tuple[int, str | None]] = []
        self.called = threading.Event()

    def execute(
        self,
        *,
        limit: int = 25,
        after_volume_id: str | None = None,
    ) -> EpubNavigationBatchResult:
        self.calls.append((limit, after_volume_id))
        self.called.set()
        outcome = next(self._outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _result(scanned: int, *, last: str | None) -> EpubNavigationBatchResult:
    return EpubNavigationBatchResult(
        scanned=scanned,
        processed=scanned,
        parse_failures=0,
        last_volume_id=last,
        may_have_more=scanned == 25,
    )


def _worker(stub: StubRebuild, tmp_path: Path) -> ReaderNavigationMaintenanceWorker:
    worker = ReaderNavigationMaintenanceWorker(
        sessionmaker[Session](),
        Settings(storage_root=str(tmp_path)),
    )
    worker._rebuild = cast(
        RebuildEpubNavigationBatch[PreparedEpubNavigationWrite], stub
    )
    return worker


def test_reader_navigation_worker_yields_and_fairly_wraps_cursor(
    tmp_path: Path,
) -> None:
    stub = StubRebuild(
        (
            _result(25, last="volume-025"),
            _result(3, last="volume-028"),
            _result(0, last=None),
            _result(0, last=None),
        )
    )
    worker = _worker(stub, tmp_path)

    assert worker._process_once() == 0.1
    assert worker._process_once() == 0.1
    assert worker._process_once() == 0.1
    assert worker._process_once() == 15.0
    assert stub.calls == [
        (25, None),
        (25, "volume-025"),
        (25, "volume-028"),
        (25, None),
    ]


def test_reader_navigation_worker_defers_and_throttles_busy_logs(
    caplog: pytest.LogCaptureFixture,
    tmp_path: Path,
) -> None:
    busy = OperationalError(
        "DELETE LibraryReadingUnit",
        {},
        sqlite3.OperationalError("database is locked"),
    )
    worker = _worker(StubRebuild((busy, busy)), tmp_path)

    with caplog.at_level(logging.WARNING):
        assert worker._process_once() == 1.0
        assert worker._process_once() == 1.0

    deferred = [
        record
        for record in caplog.records
        if "outcome=deferred reason=database_busy" in record.getMessage()
    ]
    assert len(deferred) == 1
    assert deferred[0].exc_info is None


def test_reader_navigation_worker_stop_interrupts_idle_wait(
    tmp_path: Path,
) -> None:
    stub = StubRebuild((_result(0, last=None),))
    worker = _worker(stub, tmp_path)

    worker.start()
    assert stub.called.wait(timeout=1)
    worker.stop()

    assert worker._thread is None
