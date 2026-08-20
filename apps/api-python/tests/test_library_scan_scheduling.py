from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from app.modules.imports.infrastructure.directory_scan import LibraryConfig
from app.worker.library_scanner import WorkerManager


@contextmanager
def _session_scope():
    yield object()


def test_periodic_refresh_schedules_one_root_scan_per_library(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    library = LibraryConfig(
        id="periodic-scan-library",
        root_path=str(root),
        organization_mode="FLAT",
        min_file_size_bytes=0,
    )
    persisted = []

    def persist(_db, jobs, events):
        persisted.extend(jobs)
        assert events == ()
        return len(jobs)

    monkeypatch.setattr(
        "app.worker.library_scanner.persist_import_scan_requests", persist
    )
    manager = WorkerManager(_session_scope)

    created = manager.schedule_library_scans((library,))

    assert created == 1
    assert len(persisted) == 1
    assert persisted[0].library_id == library.id
    assert persisted[0].root_path == str(root.resolve())
    assert persisted[0].trigger == "PERIODIC"


def test_paused_scanner_does_not_enqueue_root_scans(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    library = LibraryConfig(
        id="paused-scan-library",
        root_path=str(root),
        organization_mode="FLAT",
        min_file_size_bytes=0,
    )
    manager = WorkerManager(_session_scope)
    manager.pause_import_scheduling()

    assert manager.schedule_library_scans((library,)) == 0
