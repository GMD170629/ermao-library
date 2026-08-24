from pathlib import Path
from time import monotonic, sleep

from app.modules.imports.infrastructure.library_scan_watcher import (
    LibraryEventBuffer,
    LibraryScanWatcher,
    WatchedLibrary,
)


def _wait_until_ready(buffer: LibraryEventBuffer, timeout: float = 3.0) -> bool:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if buffer.ready():
            return True
        sleep(0.02)
    return False


def test_event_buffer_coalesces_and_modification_only_extends_pending_event() -> None:
    buffer = LibraryEventBuffer(quiet_seconds=5)
    buffer.extend_if_pending("library", observed_at=10)
    assert buffer.ready(observed_at=20) == ()
    buffer.mark_created("library", observed_at=10)
    buffer.extend_if_pending("library", observed_at=14)
    assert buffer.ready(observed_at=18) == ()
    assert buffer.ready(observed_at=19) == ("library",)


def test_real_watcher_reports_create_but_not_existing_file_modify(
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
        sleep(0.2)
        assert buffer.ready() == ()
        (tmp_path / "new.epub").write_bytes(b"book")
        assert _wait_until_ready(buffer)
    finally:
        watcher.shutdown()
