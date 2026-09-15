"""Watchdog adapter that buffers changed directory scopes without database I/O."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from watchdog.events import (
    FileSystemEvent,
    FileSystemEventHandler,
    FileSystemMovedEvent,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from app.modules.imports.domain.scan_policy import ScanScope, merge_scan_scopes

LibraryEventType = Literal["created", "modified", "deleted", "moved"]


@dataclass(frozen=True, slots=True)
class WatchedLibrary:
    library_id: str
    root_path: Path


@dataclass(frozen=True, slots=True)
class PendingLibraryEvents:
    library_id: str
    version: int
    scopes: tuple[ScanScope, ...]
    observed_at: float
    event_types: frozenset[LibraryEventType]


class LibraryEventBuffer:
    def __init__(self, *, quiet_seconds: float = 5.0) -> None:
        self._quiet_seconds = quiet_seconds
        self._pending: dict[str, PendingLibraryEvents] = {}
        self._version = 0
        self._lock = threading.Lock()

    def mark_changed(
        self,
        library_id: str,
        scopes: tuple[ScanScope, ...],
        *,
        observed_at: float | None = None,
        event_type: LibraryEventType = "modified",
    ) -> None:
        with self._lock:
            previous = self._pending.get(library_id)
            merged = merge_scan_scopes(previous.scopes if previous else (), scopes)
            self._version += 1
            self._pending[library_id] = PendingLibraryEvents(
                library_id,
                self._version,
                merged or (),
                time.monotonic() if observed_at is None else observed_at,
                (previous.event_types if previous else frozenset()) | {event_type},
            )

    def ready(
        self, *, observed_at: float | None = None
    ) -> tuple[PendingLibraryEvents, ...]:
        now = time.monotonic() if observed_at is None else observed_at
        with self._lock:
            return tuple(
                pending
                for pending in self._pending.values()
                if now - pending.observed_at >= self._quiet_seconds
            )

    def acknowledge(self, library_id: str, version: int) -> None:
        with self._lock:
            pending = self._pending.get(library_id)
            if pending is not None and pending.version == version:
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

    def on_created(self, event: FileSystemEvent) -> None:
        self._mark(event.src_path, recursive=event.is_directory, event_type="created")

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        self._mark(event.src_path, event_type="moved")
        self._mark(event.dest_path, recursive=event.is_directory, event_type="moved")

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._mark(event.src_path, event_type="deleted")

    def on_modified(self, event: FileSystemEvent) -> None:
        # Directory metadata notifications duplicate the concrete child event.
        if not event.is_directory:
            self._mark(event.src_path)

    def _mark(
        self,
        raw_path: bytes | str,
        *,
        recursive: bool = False,
        event_type: LibraryEventType = "modified",
    ) -> None:
        # Keep lexical paths here; containment and symlinks are checked at execution.
        path = Path(os.path.abspath(os.fsdecode(raw_path)))
        try:
            relative = path.relative_to(self._library.root_path)
        except ValueError:
            return
        parent = relative.parent.as_posix()
        scopes = [ScanScope("" if parent == "." else parent)]
        if recursive:
            scopes.append(
                ScanScope(
                    "" if relative.as_posix() == "." else relative.as_posix(), True
                )
            )
        self._buffer.mark_changed(
            self._library.library_id, tuple(scopes), event_type=event_type
        )


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

    def request_stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()

    def shutdown(self) -> None:
        observer = self._observer
        self._observer = None
        if observer is None:
            return
        observer.stop()
        observer.join()


__all__ = ["LibraryEventBuffer", "LibraryScanWatcher", "WatchedLibrary"]
