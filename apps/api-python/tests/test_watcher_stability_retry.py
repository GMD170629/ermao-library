from __future__ import annotations

from pathlib import Path
from threading import Event
from types import SimpleNamespace

import app.worker.watcher as watcher_module
import pytest
from app.worker.watcher import (
    LibraryConfig,
    WatchState,
    WorkerFileHandler,
    WorkerManager,
    WorkerRefreshProjection,
)
from sqlalchemy.exc import OperationalError
from watchdog.events import FileMovedEvent


def test_atomic_publish_rename_is_scheduled_for_monitoring(tmp_path: Path) -> None:
    source = tmp_path / "published.epub"
    folder = LibraryConfig(id="folder-1", root_path=str(tmp_path))
    scheduled: list[tuple[Path, LibraryConfig]] = []

    class RecordingManager:
        def schedule_import(
            self,
            path: Path,
            scheduled_folder: LibraryConfig,
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
    folder = LibraryConfig(
        id="folder-1",
        root_path=str(tmp_path),
        min_file_size_bytes=1,
        stability_check_enabled=True,
    )
    monkeypatch.setattr(
        watcher_module, "wait_for_stable_import_source", lambda *_args: False
    )
    monkeypatch.setattr(
        watcher_module, "_record_worker_event", lambda *_args, **_kwargs: None
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


def test_refresh_worker_state_closes_projection_session_before_path_io(
    tmp_path: Path,
    test_settings,
    monkeypatch,
) -> None:
    session_active = False

    class SessionContext:
        def __enter__(self):
            nonlocal session_active
            session_active = True
            return object()

        def __exit__(self, *_args) -> None:
            nonlocal session_active
            session_active = False

    class ObserverProbe:
        def schedule(self, *_args, **_kwargs) -> None:
            assert session_active is False

        def start(self) -> None:
            assert session_active is False

        def stop(self) -> None: ...

        def join(self, *, timeout: int) -> None: ...

    folder = LibraryConfig(id="folder-1", root_path=str(tmp_path))
    monkeypatch.setattr(
        watcher_module,
        "list_enabled_libraries",
        lambda _db: (
            [{"id": folder.id, "rootPath": folder.root_path}]
            if session_active
            else pytest.fail("read session closed")
        ),
    )
    monkeypatch.setattr(
        watcher_module,
        "get_system_settings",
        lambda _db, _keys: {} if session_active else pytest.fail("read session closed"),
    )
    monkeypatch.setattr(
        watcher_module,
        "enabled_libraries",
        lambda _rows, _settings: (
            (folder,)
            if not session_active
            else pytest.fail("projection mapping ran inside read transaction")
        ),
    )
    monkeypatch.setattr(watcher_module, "Observer", ObserverProbe)
    manager = WorkerManager(lambda: SessionContext(), test_settings)
    monkeypatch.setattr(
        manager,
        "_schedule_scan_request",
        lambda **_kwargs: (
            None
            if not session_active
            else pytest.fail("scan preparation ran inside read transaction")
        ),
    )
    monkeypatch.setattr(
        manager.security,
        "validate_library_root",
        lambda path: (
            SimpleNamespace(real_path=Path(path))
            if not session_active
            else pytest.fail("path IO ran inside read transaction")
        ),
    )

    manager.refresh_worker_state()

    assert "folder-1" in manager.watchers


def test_manual_rescan_prepares_all_folders_before_one_database_checkpoint(
    tmp_path: Path,
    test_settings,
    monkeypatch,
) -> None:
    session_active = False
    session_count = 0

    class SessionContext:
        def __enter__(self):
            nonlocal session_active, session_count
            session_active = True
            session_count += 1
            return object()

        def __exit__(self, *_args) -> None:
            nonlocal session_active
            session_active = False

    folders = (
        LibraryConfig(id="folder-1", root_path=str(tmp_path / "one")),
        LibraryConfig(id="folder-2", root_path=str(tmp_path / "two")),
    )
    persisted_scan_jobs = []

    def persist_checkpoint(_db, **kwargs) -> int:
        assert session_active is True
        persisted_scan_jobs.extend(kwargs["scan_jobs"])
        return len(kwargs["scan_jobs"])

    manager = WorkerManager(SessionContext, test_settings)
    monkeypatch.setattr(
        manager.security,
        "validate_library_root",
        lambda path: (
            SimpleNamespace(real_path=Path(path))
            if not session_active
            else pytest.fail("path validation ran inside write transaction")
        ),
    )
    monkeypatch.setattr(
        watcher_module,
        "persist_import_rescan_completion",
        persist_checkpoint,
    )

    manager.process_rescan_requests(
        WorkerRefreshProjection(
            folders=folders,
            rescan_requested_at='{"requestedAt":"2026-08-11T10:00:00Z"}',
            rescan_handled_at=None,
        )
    )

    assert session_count == 1
    assert {request.library_id for request in persisted_scan_jobs} == {
        "folder-1",
        "folder-2",
    }


def test_watcher_retries_a_transient_database_lock_without_losing_event(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "locked.epub"
    source.write_bytes(b"book")
    folder = LibraryConfig(id="folder-locked", root_path=str(tmp_path))
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
        watcher_module, "prepare_import_enqueue_command", lambda path, **_kwargs: path
    )
    monkeypatch.setattr(
        watcher_module,
        "load_import_enqueue_command_projection",
        lambda _db, _command: object(),
    )
    monkeypatch.setattr(
        watcher_module,
        "prepare_import_enqueue_write",
        lambda command, _projection, **_kwargs: command,
    )
    monkeypatch.setattr(
        watcher_module,
        "persist_import_enqueue_write",
        lambda _db, prepared: enqueued.append(prepared),
    )
    monkeypatch.setattr(watcher_module.time, "sleep", lambda _seconds: None)

    manager = WorkerManager(
        db_factory,
        SimpleNamespace(monitor_root=str(tmp_path)),
    )
    manager.schedule_import(source, folder, state)

    assert factory_calls == 4
    assert enqueued == [source]


def test_watcher_recovers_exhausted_database_lock_with_folder_scan(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "still-locked.epub"
    source.write_bytes(b"book")
    folder = LibraryConfig(id="folder-recovery", root_path=str(tmp_path))
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
        manager,
        "_schedule_scan_request",
        lambda **kwargs: recovery_scans.append(
            (
                kwargs["library_id"],
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
    folder = LibraryConfig(
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
        "prepare_import_enqueue_command",
        lambda *_args, **_kwargs: pytest.fail(
            "audio watcher events must not create file-level import tasks"
        ),
    )
    manager = WorkerManager(
        SessionContext,
        SimpleNamespace(monitor_root=str(tmp_path)),
    )
    monkeypatch.setattr(
        manager,
        "_schedule_scan_request",
        lambda **kwargs: scheduled.append(kwargs),
    )

    manager.schedule_import(source, folder, state)
    manager.schedule_import(source, folder, state)

    assert len(scheduled) == 2
    assert all(item["root_path"] == tmp_path for item in scheduled)
    assert all(item["trigger"] == "WATCHER_AUDIO_EVENT" for item in scheduled)
    assert all(item["available_at"] is not None for item in scheduled)
