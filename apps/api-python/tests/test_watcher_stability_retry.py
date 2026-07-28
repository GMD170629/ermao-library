from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from threading import Event
from time import monotonic, sleep

from watchdog.events import FileMovedEvent

import app.worker.watcher as watcher_module
from app.worker.watcher import (
    ImportQueue,
    MonitorFolderConfig,
    WatchState,
    WorkerFileHandler,
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


def test_import_queue_retries_when_a_file_changes_during_stability_check(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "large.epub"
    source.write_bytes(b"initial")
    checking_started = Event()
    completed = Event()
    calls: list[Path] = []

    def defer_then_complete(
        _db,
        _settings,
        path,
        _folder,
        *,
        has_changed=None,
        mark_deferred=None,
    ) -> bool:
        calls.append(path)
        if len(calls) == 1:
            checking_started.set()
            deadline = monotonic() + 2
            while (
                has_changed is not None and not has_changed() and monotonic() < deadline
            ):
                sleep(0.01)
            assert has_changed is not None and has_changed()
            return False
        completed.set()
        return True

    monkeypatch.setattr(watcher_module, "import_watched_file", defer_then_complete)
    queue = ImportQueue(lambda: nullcontext(object()), object())
    folder = MonitorFolderConfig(
        id="folder-1",
        root_path=str(tmp_path),
        min_file_size_bytes=1,
        stability_check_seconds=0,
    )
    try:
        queue.enqueue(source, folder)
        assert checking_started.wait(timeout=2)
        source.write_bytes(b"changed while the first check was pending")
        queue.enqueue(source, folder)
        assert completed.wait(timeout=2)
        assert calls == [source.resolve(), source.resolve()]
    finally:
        queue.stop()


def test_import_queue_retries_when_stability_check_defers_without_a_second_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "growing.epub"
    source.write_bytes(b"initial")
    completed = Event()
    calls: list[Path] = []

    def defer_then_complete(
        _db,
        _settings,
        path,
        _folder,
        *,
        has_changed=None,
        mark_deferred=None,
    ) -> bool:
        calls.append(path)
        if len(calls) == 1:
            assert mark_deferred is not None
            mark_deferred()
            return False
        completed.set()
        return True

    monkeypatch.setattr(watcher_module, "import_watched_file", defer_then_complete)
    queue = ImportQueue(lambda: nullcontext(object()), object())
    folder = MonitorFolderConfig(
        id="folder-1",
        root_path=str(tmp_path),
        min_file_size_bytes=1,
        stability_check_seconds=0,
    )
    try:
        queue.enqueue(source, folder)
        assert completed.wait(timeout=2)
        assert calls == [source.resolve(), source.resolve()]
    finally:
        queue.stop()


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
