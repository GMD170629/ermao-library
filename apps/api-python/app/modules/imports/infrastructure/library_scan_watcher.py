"""Watchdog adapter that buffers create and move-in events without database I/O."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileSystemMovedEvent,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver


@dataclass(frozen=True, slots=True)
class WatchedLibrary:
    library_id: str
    root_path: Path


class LibraryEventBuffer:
    def __init__(self, *, quiet_seconds: float = 5.0) -> None:
        self._quiet_seconds = quiet_seconds
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def mark_created(
        self, library_id: str, *, observed_at: float | None = None
    ) -> None:
        with self._lock:
            self._pending[library_id] = (
                time.monotonic() if observed_at is None else observed_at
            )

    def extend_if_pending(
        self, library_id: str, *, observed_at: float | None = None
    ) -> None:
        with self._lock:
            if library_id in self._pending:
                self._pending[library_id] = (
                    time.monotonic() if observed_at is None else observed_at
                )

    def ready(self, *, observed_at: float | None = None) -> tuple[str, ...]:
        now = time.monotonic() if observed_at is None else observed_at
        with self._lock:
            return tuple(
                library_id
                for library_id, last_event_at in self._pending.items()
                if now - last_event_at >= self._quiet_seconds
            )

    def acknowledge(self, library_id: str) -> None:
        with self._lock:
            self._pending.pop(library_id, None)

    def retain(self, library_ids: set[str]) -> None:
        with self._lock:
            self._pending = {
                library_id: observed_at
                for library_id, observed_at in self._pending.items()
                if library_id in library_ids
            }


class _LibraryEventHandler(FileSystemEventHandler):
    def __init__(self, library: WatchedLibrary, buffer: LibraryEventBuffer) -> None:
        self._library = library
        self._buffer = buffer
        self._known_paths = {library.root_path.resolve(strict=False)} | {
            path.resolve(strict=False) for path in library.root_path.rglob("*")
        }

    def on_created(self, event: FileSystemEvent) -> None:
        path = Path(os.fsdecode(event.src_path)).resolve(strict=False)
        if path in self._known_paths:
            return
        self._known_paths.add(path)
        self._buffer.mark_created(self._library.library_id)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        source = Path(os.fsdecode(event.src_path)).resolve(strict=False)
        destination = Path(os.fsdecode(event.dest_path)).resolve(strict=False)
        self._known_paths.discard(source)
        if self._is_inside_root(destination):
            self._known_paths.add(destination)
        if not self._is_inside_root(source) and self._is_inside_root(destination):
            self._buffer.mark_created(self._library.library_id)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._known_paths.discard(
            Path(os.fsdecode(event.src_path)).resolve(strict=False)
        )

    def on_modified(self, event: FileSystemEvent) -> None:
        self._buffer.extend_if_pending(self._library.library_id)

    def _is_inside_root(self, path: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(self._library.root_path)
            return True
        except ValueError:
            return False


class LibraryScanWatcher:
    """Own one observer thread and replace it atomically when roots change."""

    def __init__(self, buffer: LibraryEventBuffer) -> None:
        self._buffer = buffer
        self._observer: BaseObserver | None = None
        self._signature: tuple[tuple[str, str], ...] = ()
        self._configured = False

    def reconcile(
        self, libraries: tuple[WatchedLibrary, ...], *, enabled: bool
    ) -> bool:
        signature = (
            tuple(sorted((item.library_id, str(item.root_path)) for item in libraries))
            if enabled
            else ()
        )
        changed = not self._configured or signature != self._signature
        if not changed and (not signature or self._observer is not None):
            return False
        self.shutdown()
        self._signature = signature
        self._configured = True
        if not signature:
            return changed
        observer = Observer()
        scheduled = 0
        for library in libraries:
            if not library.root_path.is_dir():
                continue
            observer.schedule(
                _LibraryEventHandler(library, self._buffer),
                str(library.root_path),
                recursive=True,
            )
            scheduled += 1
        if scheduled:
            observer.start()
            self._observer = observer
        return changed

    def shutdown(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is None:
            return
        observer.stop()
        observer.join(timeout=5)


__all__ = ["LibraryEventBuffer", "LibraryScanWatcher", "WatchedLibrary"]
