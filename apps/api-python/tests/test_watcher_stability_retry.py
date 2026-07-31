from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError
from watchdog.events import FileMovedEvent

import app.worker.watcher as watcher_module
from app.worker.watcher import (
    MonitorFolderConfig,
    WatchState,
    WorkerFileHandler,
    WorkerManager,
)


def test_atomic_publish_rename_is_scheduled_for_monitoring(tmp_path: Path) -> None:
    source = tmp_path / "published.epub"
    folder = MonitorFolderConfig(id="folder-1", root_path=str(tmp_path))
    scheduled: list[tuple[Path, MonitorFolderConfig]] = []

    class RecordingManager:
        def schedule_import(
            self,
            path: Path,
            scheduled_folder: MonitorFolderConfig,
            _state: WatchState,
        ) -> None:
            scheduled.append((path, scheduled_folder))

    handler = WorkerFileHandler(
        RecordingManager(),
        folder,
        WatchState(observer=object(), root_path=tmp_path, config_signature="test"),
    )
    handler.on_moved(FileMovedEvent(str(tmp_path / ".upload-123.part"), str(source)))

    assert scheduled == [(source, folder)]


def test_unstable_file_marks_a_retry_after_it_reaches_the_minimum_size(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "changed.epub"
    source.write_bytes(b"content")
    deferred = Event()
    folder = MonitorFolderConfig(
        id="folder-1",
        root_path=str(tmp_path),
        min_file_size_bytes=1,
        stability_check_enabled=True,
    )
    monkeypatch.setattr(
        watcher_module, "wait_for_stable_import_source", lambda *_args: False
    )
    monkeypatch.setattr(
        watcher_module, "record_system_event", lambda *_args, **_kwargs: None
    )

    imported = watcher_module.import_watched_file(
        object(),
        object(),
        source,
        folder,
        mark_deferred=deferred.set,
    )

    assert imported is False
    assert deferred.is_set()


def test_watcher_retries_a_transient_database_lock_without_losing_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "locked.epub"
    source.write_bytes(b"book")
    folder = MonitorFolderConfig(id="folder-locked", root_path=str(tmp_path))
    state = WatchState(observer=object(), root_path=tmp_path, config_signature="test")
    factory_calls = 0
    enqueued: list[Path] = []

    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args) -> None:
            return None

    def db_factory() -> SessionContext:
        nonlocal factory_calls
        factory_calls += 1
        return SessionContext()

    def high_watermark(_db) -> bool:
        if factory_calls == 1:
            raise OperationalError(
                "queue capacity",
                {},
                RuntimeError("database is locked"),
            )
        return False

    monkeypatch.setattr(
        watcher_module, "import_queue_at_high_watermark", high_watermark
    )
    monkeypatch.setattr(
        watcher_module,
        "enqueue_import_task",
        lambda _db, path, **_kwargs: enqueued.append(path),
    )
    monkeypatch.setattr(watcher_module.time, "sleep", lambda _seconds: None)

    manager = WorkerManager(
        db_factory,
        SimpleNamespace(monitor_root=str(tmp_path)),
    )
    manager.schedule_import(source, folder, state)

    assert factory_calls == 2
    assert enqueued == [source]


def test_watcher_recovers_exhausted_database_lock_with_folder_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "still-locked.epub"
    source.write_bytes(b"book")
    folder = MonitorFolderConfig(id="folder-recovery", root_path=str(tmp_path))
    state = WatchState(observer=object(), root_path=tmp_path, config_signature="test")
    recovery_scans: list[tuple[str, Path, str]] = []

    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(
        watcher_module,
        "import_queue_at_high_watermark",
        lambda _db: (_ for _ in ()).throw(
            OperationalError(
                "queue capacity",
                {},
                RuntimeError("database is locked"),
            )
        ),
    )
    monkeypatch.setattr(watcher_module.time, "sleep", lambda _seconds: None)
    manager = WorkerManager(
        SessionContext,
        SimpleNamespace(monitor_root=str(tmp_path)),
    )
    manager.watchers[folder.id] = state

    manager.schedule_import(source, folder, state)

    monkeypatch.setattr(
        watcher_module,
        "schedule_import_scan_job",
        lambda _db, **kwargs: recovery_scans.append(
            (
                kwargs["monitor_folder_id"],
                kwargs["root_path"],
                kwargs["trigger"],
            )
        ),
    )
    manager._schedule_pending_recovery_scans()

    assert recovery_scans == [(folder.id, tmp_path, "WATCHER_RECOVERY")]
    assert manager._pending_scan_recovery_folder_ids == set()


def test_watcher_audio_events_debounce_into_delayed_directory_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "001.mp3"
    source.write_bytes(b"audio")
    folder = MonitorFolderConfig(
        id="folder-audio-watch",
        root_path=str(tmp_path),
        stability_check_enabled=True,
        stability_check_seconds=3,
    )
    state = WatchState(observer=object(), root_path=tmp_path, config_signature="test")
    scheduled: list[dict[str, object]] = []

    class SessionContext:
        def __enter__(self):
            return object()

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(
        watcher_module, "import_queue_at_high_watermark", lambda _db: False
    )
    monkeypatch.setattr(
        watcher_module,
        "schedule_import_scan_job",
        lambda _db, **kwargs: scheduled.append(kwargs),
    )
    monkeypatch.setattr(
        watcher_module,
        "enqueue_import_task",
        lambda *_args, **_kwargs: pytest.fail(
            "audio watcher events must not create file-level import tasks"
        ),
    )
    manager = WorkerManager(
        SessionContext,
        SimpleNamespace(monitor_root=str(tmp_path)),
    )

    manager.schedule_import(source, folder, state)
    manager.schedule_import(source, folder, state)

    assert len(scheduled) == 2
    assert all(item["root_path"] == tmp_path for item in scheduled)
    assert all(item["trigger"] == "WATCHER_AUDIO_EVENT" for item in scheduled)
    assert all(item["available_at"] is not None for item in scheduled)
