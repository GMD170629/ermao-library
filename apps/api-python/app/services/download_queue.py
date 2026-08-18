from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.bootstrap.download import enqueue_download_import_command
from app.core.config import Settings
from app.modules.download.infrastructure.tasks import (
    has_table,
    list_enabled_libraries,
    next_queued_download_task,
)
from app.modules.imports.public import is_supported_import_filename
from app.services.download_executor import execute_download_task
from app.services.queue_runtime import QueueHeartbeatPump


class DownloadQueueWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        heartbeat_db_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self._stop_event = threading.Event()
        self._process_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="shuku-download-queue", daemon=True
        )
        self._instance_id = f"download-{uuid4().hex}"
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory or db_factory,
            queue_name="download",
            instance_id=self._instance_id,
            poll_interval_seconds=settings.download_queue_interval_seconds,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def process_once(self) -> bool:
        if not self._process_lock.acquire(blocking=False):
            return False
        try:
            with self.db_factory() as db:
                return process_next_download_task(db, self.settings)
        except Exception as exc:  # noqa: BLE001 - worker iteration containment.
            print(f"[download-queue] task processing failed: {exc}", flush=True)
            return False
        finally:
            self._process_lock.release()

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            while not self._stop_event.is_set():
                processed = self.process_once()
                self._heartbeat.pulse(processed=processed, error=None)
                if processed:
                    continue
                self._stop_event.wait(self.settings.download_queue_interval_seconds)
        finally:
            self._heartbeat.stop()


def next_queued_task(db: Session) -> dict[str, Any] | None:
    try:
        return next_queued_download_task(db)
    except SQLAlchemyError as exc:
        print(
            f"[download-queue] download task table unavailable, retrying later: {exc}",
            flush=True,
        )
        return None


def process_next_download_task(db: Session, settings: Settings) -> bool:
    task = next_queued_task(db)
    db.close()
    if not task:
        return False
    result = execute_download_task(db, settings, str(task["id"]))
    if result.task.get("status") == "downloaded":
        downloaded_path = Path(str(result.task.get("filePath") or "")).expanduser()
        if downloaded_path.is_file() and is_supported_import_filename(downloaded_path):
            try:
                library_id = _library_id(db, downloaded_path)
                db.close()
                import_task = enqueue_download_import_command(
                    db,
                    task_id=str(task["id"]),
                    source_path=str(downloaded_path),
                    original_name=downloaded_path.name,
                    library_id=library_id,
                )
                print(
                    f"[download-queue] downloaded {task['id']} and queued import {import_task.id}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - import handoff containment.
                print(
                    f"[download-queue] downloaded {task['id']} but import enqueue failed: {exc}",
                    flush=True,
                )
    return True


def _library_id(db: Session, path: Path) -> str | None:
    if not has_table(db, "Library"):
        db.close()
        return None
    folders = list_enabled_libraries(db)
    db.close()
    resolved = path.resolve()
    matches: list[tuple[int, str]] = []
    for folder in folders:
        try:
            root = Path(str(folder["rootPath"])).expanduser().resolve()
        except OSError:
            continue
        if resolved == root or root in resolved.parents:
            matches.append((len(root.parts), str(folder["id"])))
    return max(matches, default=(0, None))[1]


def start_download_queue_worker(
    db_factory: Callable[[], Session],
    settings: Settings,
    heartbeat_db_factory: Callable[[], Session] | None = None,
) -> DownloadQueueWorker | None:
    if not settings.download_queue_enabled:
        return None
    worker = DownloadQueueWorker(db_factory, settings, heartbeat_db_factory)
    worker.start()
    return worker
