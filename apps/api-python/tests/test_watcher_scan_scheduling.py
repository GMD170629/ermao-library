from __future__ import annotations

from pathlib import Path
from typing import cast

from watchdog.observers import Observer

from app.modules.imports.infrastructure.directory_scan import LibraryConfig
from app.worker.watcher import WatchState, WorkerManager


def test_watcher_event_schedules_library_root_scan(
    test_settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "library"
    root.mkdir()
    source = root / "book.epub"
    source.write_bytes(b"epub")
    folder = LibraryConfig(
        id="watcher-scan-library",
        root_path=str(root),
        organization_mode="FLAT",
        min_file_size_bytes=0,
        stability_check_enabled=False,
    )
    state = WatchState(
        observer=cast(Observer, object()),
        root_path=root,
        config_signature="test",
    )
    manager = WorkerManager(lambda: None, test_settings)
    scheduled: list[dict[str, object]] = []
    monkeypatch.setattr(
        manager,
        "_schedule_scan_request",
        lambda **values: scheduled.append(values),
    )

    manager.schedule_import(source, folder, state)

    assert scheduled == [
        {
            "library_id": folder.id,
            "root_path": root,
            "trigger": "watcher_event",
            "available_at": None,
        }
    ]
