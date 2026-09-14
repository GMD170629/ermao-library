from pathlib import Path
from time import monotonic, sleep

from watchdog.events import (
    DirCreatedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
)

from app.modules.imports.domain.scan_policy import ScanScope
from app.modules.imports.infrastructure.library_scan_watcher import (
    LibraryEventBuffer,
    LibraryScanWatcher,
    WatchedLibrary,
    _LibraryEventHandler,
)


def _wait_until_ready(buffer: LibraryEventBuffer, timeout: float = 3.0) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if buffer.ready():
            return True
        sleep(0.02)
    return False


def test_event_buffer_coalesces_without_acknowledging_newer_events() -> None:
    buffer = LibraryEventBuffer(quiet_seconds=5)
    buffer.mark_changed("library", (ScanScope("a"),), observed_at=10)
    first = buffer.ready(observed_at=20)[0]
    buffer.mark_changed("library", (ScanScope("b"),), observed_at=14)
    buffer.acknowledge("library", first.version)
    assert buffer.ready(observed_at=18) == ()
    pending = buffer.ready(observed_at=19)[0]
    assert pending.scopes == (ScanScope("a"), ScanScope("b"))
    buffer.acknowledge("library", pending.version)
    assert buffer.ready(observed_at=20) == ()


def test_real_watcher_reports_create_and_existing_file_modify(
    tmp_path: Path,
) -> None:
    existing = tmp_path / "existing.epub"
    existing.write_bytes(b"before")
    buffer = LibraryEventBuffer(quiet_seconds=0.1)
    watcher = LibraryScanWatcher(buffer)
    try:
        watcher.reconcile(
            (WatchedLibrary("library", tmp_path.resolve()),), enabled=True
        )
        existing.write_bytes(b"after")
        assert _wait_until_ready(buffer)
        pending = buffer.ready()[0]
        buffer.acknowledge(pending.library_id, pending.version)
        (tmp_path / "new.epub").write_bytes(b"book")
        assert _wait_until_ready(buffer)
    finally:
        watcher.shutdown()


def test_event_paths_cover_both_move_parents_and_new_subtrees(tmp_path: Path) -> None:
    buffer = LibraryEventBuffer(quiet_seconds=0)
    handler = _LibraryEventHandler(WatchedLibrary("library", tmp_path), buffer)
    handler.on_created(FileCreatedEvent(str(tmp_path / "a/new.epub")))
    handler.on_modified(FileModifiedEvent(str(tmp_path / "b/book.epub")))
    handler.on_deleted(FileDeletedEvent(str(tmp_path / "c/old.epub")))
    handler.on_moved(
        FileMovedEvent(str(tmp_path / "d/book.epub"), str(tmp_path / "e/book.epub"))
    )
    handler.on_created(DirCreatedEvent(str(tmp_path / "f/nested")))
    pending = buffer.ready()[0]
    assert pending.event_types == {"created", "modified", "deleted", "moved"}
    assert set(pending.scopes) == {
        ScanScope("a"),
        ScanScope("b"),
        ScanScope("c"),
        ScanScope("d"),
        ScanScope("e"),
        ScanScope("f"),
        ScanScope("f/nested", True),
    }


def test_move_out_and_move_in_only_mark_library_side(tmp_path: Path) -> None:
    buffer = LibraryEventBuffer(quiet_seconds=0)
    handler = _LibraryEventHandler(
        WatchedLibrary("library", tmp_path / "books"), buffer
    )
    handler.on_moved(
        FileMovedEvent(
            str(tmp_path / "books/a/book.epub"), str(tmp_path / "outside.epub")
        )
    )
    handler.on_moved(
        FileMovedEvent(
            str(tmp_path / "outside.epub"), str(tmp_path / "books/b/book.epub")
        )
    )
    assert buffer.ready()[0].scopes == (ScanScope("a"), ScanScope("b"))
