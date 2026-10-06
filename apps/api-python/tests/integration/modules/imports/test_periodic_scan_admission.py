"""Periodic scans skip busy libraries and stop when the schedule is disabled."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.bootstrap.imports import (
    get_library_scan_settings,
    update_library_scan_settings,
)
from app.bootstrap.library_scan_runtime import LibraryScanCoordinator
from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
from app.models import Library, LibraryBook, LibraryImportTask, LibrarySourceNode
from app.models.settings import SystemSetting
from app.modules.imports.application.readable_resource.book_work import BookWork
from app.modules.imports.application.readable_resource.request_library_scan import (
    RequestLibraryScanCommand,
)
from app.modules.imports.domain.library_scan_schedule import LibraryScanSettings
from app.modules.imports.infrastructure.library_scan_watcher import WatchedLibrary
from app.modules.imports.infrastructure.readable_resource.support import (
    SqlAlchemyUnitOfWork,
)
from app.modules.library.public import SourceNodeRelativePath


def _book(db):
    db.add(LibrarySourceNode(
        id="source", library_id="test-library", relative_path="book.epub",
        path_key=SourceNodeRelativePath("book.epub").path_key, name="book.epub",
        physical_kind="REGULAR_FILE", observed_size_bytes=1, observed_mtime_ns=1,
        observed_at=datetime.now(UTC),
    ))
    db.flush()
    db.add(LibraryBook(id="book", library_id="test-library", source_node_id="source"))
    db.commit()


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING"])
@pytest.mark.parametrize("kind", ["SCAN_LIBRARY", "CONTINUE_SOURCE", "IMPORT_BOOK"])
def test_periodic_scan_skips_every_active_task_kind(db_session, test_settings, kind, state):
    _book(db_session)
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    if kind == "IMPORT_BOOK":
        active = pipeline.queue.request_book_work(
            book_id="book", work=BookWork(identify=True), requested_at=datetime.now(UTC)
        )
    else:
        active = pipeline.queue.enqueue(
            kind=kind, library_id="test-library",
            source_node_id="source" if kind == "CONTINUE_SOURCE" else None,
        )
    row = db_session.get(LibraryImportTask, active.id)
    row.state = state
    db_session.commit()
    command = RequestLibraryScanCommand(library_id="test-library", trigger="PERIODIC")
    for _ in range(3):
        result = pipeline.request_library_scan.execute(command)
        assert result.enqueued is False and result.task_id is None
    assert list(db_session.scalars(select(LibraryImportTask.id))) == [active.id]
    row = db_session.get(LibraryImportTask, active.id)
    row.state = "SUCCEEDED"
    db_session.commit()
    result = pipeline.request_library_scan.execute(command)
    assert result.enqueued
    assert db_session.get(LibraryImportTask, result.task_id).kind == "SCAN_LIBRARY"


def test_other_library_work_does_not_block_periodic_scan(db_session, test_settings, tmp_path):
    db_session.add(Library(
        id="other", name="Other", root_path=str(tmp_path / "other"), organization_mode="FLAT"
    ))
    db_session.commit()
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    pipeline.queue.enqueue(kind="SCAN_LIBRARY", library_id="other")
    db_session.commit()
    assert pipeline.request_library_scan.execute(RequestLibraryScanCommand(
        library_id="test-library", trigger="PERIODIC"
    )).enqueued


def test_disabling_schedule_blocks_scheduled_admission_but_allows_manual(db_session, test_settings):
    _book(db_session)
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    book = pipeline.queue.request_book_work(
        book_id="book", work=BookWork(identify=True), requested_at=datetime.now(UTC)
    )
    db_session.commit()
    update_library_scan_settings(
        db_session, LibraryScanSettings(interval_minutes=0)
    )
    assert set(db_session.scalars(select(LibraryImportTask.id))) == {book.id}
    assert not pipeline.request_library_scan.execute(RequestLibraryScanCommand(
        library_id="test-library", trigger="PERIODIC"
    )).enqueued
    assert pipeline.request_library_scan.execute(RequestLibraryScanCommand(
        library_id="test-library", trigger="MANUAL"
    )).enqueued


def _coordinator(db, request):
    coordinator = LibraryScanCoordinator(
        session=db, request_scan=request, uow=SqlAlchemyUnitOfWork(db)
    )
    coordinator._watcher = Mock(reconcile=Mock(return_value=False))
    return coordinator


@pytest.mark.parametrize("stored_minutes", [None, 0, 5, 30, 60, 1440])
def test_existing_settings_only_schedule_at_twenty_four_hours(
    db_session, test_settings, monkeypatch, stored_minutes
):
    if stored_minutes is not None:
        db_session.add(SystemSetting(
            key="libraryScan.intervalMinutes", value=str(stored_minutes)
        ))
        db_session.commit()
    expected_minutes = 0 if stored_minutes == 0 else 1440
    assert get_library_scan_settings(db_session).interval_minutes == expected_minutes

    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    clock = Mock(now=Mock(return_value=now))
    monkeypatch.setattr("app.bootstrap.library_scan_runtime.datetime", clock)
    request = Mock()
    coordinator = _coordinator(db_session, request)
    coordinator.tick()
    if expected_minutes == 0:
        assert coordinator._next_periodic_at is None
        request.execute.assert_not_called()
    else:
        assert coordinator._next_periodic_at == now + timedelta(hours=24)
        assert [call.args[0].trigger for call in request.execute.call_args_list] == ["STARTUP"]

    request.execute.reset_mock()
    clock.now.return_value = now + timedelta(hours=23, minutes=59)
    coordinator.tick()
    request.execute.assert_not_called()
    clock.now.return_value = now + timedelta(hours=24)
    coordinator.tick()
    assert [call.args[0].trigger for call in request.execute.call_args_list] == (
        [] if expected_minutes == 0 else ["PERIODIC"]
    )


@pytest.mark.parametrize("interval_ms", [300_000, 1_800_000, 3_600_000])
def test_legacy_environment_interval_cannot_shorten_periodic_scans(
    db_session, test_settings, monkeypatch, interval_ms
):
    test_settings.library_scan_interval_ms = interval_ms
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    monkeypatch.setattr(
        "app.bootstrap.library_scan_runtime.datetime", Mock(now=Mock(return_value=now))
    )
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    coordinator = _coordinator(db_session, pipeline.request_library_scan)
    coordinator.tick()
    assert coordinator._next_periodic_at == now + timedelta(hours=24)


def test_failed_periodic_request_waits_for_next_interval(db_session, test_settings, caplog):
    request = Mock()
    calls = []

    def execute(command):
        calls.append(command.library_id)
        if command.library_id == "failing":
            raise OSError(13, "synthetic enqueue failure")

    request.execute.side_effect = execute
    coordinator = _coordinator(db_session, request)
    coordinator._next_refresh_at = float("inf")
    coordinator._libraries = tuple(WatchedLibrary(name, Path(".")) for name in ("healthy", "failing"))
    coordinator._next_periodic_at = datetime.now(UTC) - timedelta(seconds=1)
    for _ in range(4):
        coordinator.tick()
    assert calls == ["healthy", "failing"]
    assert coordinator._next_periodic_at > datetime.now(UTC)
    assert "library_scan.request_failed" in caplog.text
    assert "synthetic enqueue failure" in caplog.text


def test_disabled_schedule_stays_off_across_startup_refresh_and_reenable(db_session, test_settings):
    update_library_scan_settings(
        db_session, LibraryScanSettings(interval_minutes=0)
    )
    request = Mock()
    coordinator = _coordinator(db_session, request)
    for _ in range(3):
        coordinator._next_refresh_at = 0
        coordinator.tick()
    request.execute.assert_not_called()
    assert coordinator._next_periodic_at is None
    update_library_scan_settings(
        db_session, LibraryScanSettings(interval_minutes=1440)
    )
    coordinator._next_refresh_at = 0
    coordinator.tick()
    assert coordinator._next_periodic_at > datetime.now(UTC)
    coordinator._next_periodic_at = datetime.now(UTC) - timedelta(seconds=1)
    coordinator.tick()
    assert [call.args[0].trigger for call in request.execute.call_args_list] == ["PERIODIC"]


def test_failed_startup_request_is_not_retried_every_tick(db_session, test_settings):
    request = Mock()
    request.execute.side_effect = OSError(13, "startup enqueue failure")
    coordinator = _coordinator(db_session, request)
    for _ in range(3):
        coordinator.tick()
    assert request.execute.call_count == 1
