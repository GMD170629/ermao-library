from __future__ import annotations

import logging
import os
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from watchdog.events import (
    DirCreatedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileMovedEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from appv2.modules.ingestion.contracts import MonitorFolder

logger = logging.getLogger(__name__)


class _CreatedOrMovedHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self._callback = callback

    def on_created(self, event: DirCreatedEvent | FileCreatedEvent) -> None:
        if not event.is_directory:
            self._callback(os.fsdecode(event.src_path))

    def on_moved(self, event: DirMovedEvent | FileMovedEvent) -> None:
        if not event.is_directory:
            self._callback(os.fsdecode(event.dest_path))


class MonitorWatcher:
    def __init__(
        self,
        *,
        monitor_root: Path | None,
        folders: Callable[[], list[MonitorFolder]],
        request_scan: Callable[[uuid.UUID], object],
    ) -> None:
        self._root = monitor_root.expanduser().resolve() if monitor_root else None
        self._folders = folders
        self._request_scan = request_scan
        self._observer: BaseObserver | None = None
        self._lock = threading.Lock()
        self._pending: set[uuid.UUID] = set()

    def start(self) -> None:
        if self._root is None or not self._root.is_dir() or self._observer is not None:
            return
        observer = Observer()
        observer.schedule(
            _CreatedOrMovedHandler(self._handle_path),
            str(self._root),
            recursive=True,
        )
        observer.start()
        self._observer = observer
        logger.info("monitor watcher started for %s", self._root)

    def stop(self) -> None:
        observer = self._observer
        if observer is None:
            return
        observer.stop()
        observer.join(timeout=10)
        self._observer = None

    def _handle_path(self, source_path: str) -> None:
        source = Path(source_path).resolve()
        candidates = [
            folder
            for folder in self._folders()
            if folder.enabled and source.is_relative_to(Path(folder.path))
        ]
        if not candidates:
            return
        folder = max(candidates, key=lambda item: len(Path(item.path).parts))
        with self._lock:
            if folder.id in self._pending:
                return
            self._pending.add(folder.id)
        try:
            self._request_scan(folder.id)
        except Exception:
            logger.exception("failed to enqueue event scan for %s", folder.path)
        finally:
            with self._lock:
                self._pending.discard(folder.id)
