from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.modules.imports.infrastructure.library_queries import get_import_task_by_id
from app.modules.imports.infrastructure.tasks import (
    build_import_task_values,
    claim_next_import_task as claim_next_import_task_row,
    fail_claimed_import_task_row,
    find_existing_import_task,
    insert_import_task_with_assets,
    link_imported_work_to_monitor_shelf,
    mark_download_task_completed_for_import,
    recover_stale_import_tasks as recover_stale_import_tasks_rows,
)
from app.services.queue_runtime import QueueHeartbeatPump
from app.worker.importer import ImportOptions, ImportResult, import_managed_book


def _now() -> int:
    return now_timestamp_ms()


def _id() -> str:
    return f"py_{time.time_ns()}"


def enqueue_import_task(
    db: Session,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    work_id: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[dict[str, Any], bool]:
    source = Path(source_path).expanduser().resolve()
    existing = find_existing_import_task(
        db,
        str(source),
        allow_terminal_requeue=allow_terminal_requeue,
    )
    if existing:
        return existing, False
    now = _now()
    values, bundle_files = build_import_task_values(
        task_id=_id(),
        source=source,
        origin=origin,
        original_name=original_name,
        requested_title=requested_title,
        requested_author=requested_author,
        work_id=work_id,
        monitor_folder_id=monitor_folder_id,
        message=message,
        now=now,
    )
    task = insert_import_task_with_assets(db, values, bundle_files=bundle_files, now=now)
    db.commit()
    return get_import_task_by_id(db, str(task["id"])) or task, True


def recover_stale_import_tasks(db: Session) -> int:
    recovered = recover_stale_import_tasks_rows(
        db,
        now=_now(),
        message="后台任务恢复后重新排队",
    )
    db.commit()
    return recovered


def claim_next_import_task(db: Session, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    task = claim_next_import_task_row(
        db,
        worker_id,
        lease_seconds=lease_seconds,
        now=now_timestamp_ms(),
    )
    db.commit()
    return task


def _add_work_to_shelf(db: Session, monitor_folder_id: str | None, work_id: str) -> None:
    link_imported_work_to_monitor_shelf(
        db,
        monitor_folder_id,
        work_id,
        created_at=_now(),
    )
    db.commit()


def process_import_task(db: Session, settings: Settings, task: dict[str, Any]) -> ImportResult:
    result = import_managed_book(
        db,
        settings,
        ImportOptions(
            source_file_path=Path(str(task["sourcePath"])),
            original_name=task.get("originalName"),
            requested_title=task.get("requestedTitle"),
            requested_author=task.get("requestedAuthor"),
            origin=str(task.get("origin") or "MANUAL"),
            monitor_folder_id=task.get("monitorFolderId"),
            import_task_id=str(task["id"]),
            requested_work_id=task.get("workId"),
        ),
    )
    _add_work_to_shelf(db, task.get("monitorFolderId"), result.work_id)
    mark_download_task_completed_for_import(
        db,
        source_path=str(task["sourcePath"]),
        book_id=result.work_id,
        updated_at=_now(),
    )
    db.commit()
    return result


def fail_claimed_import_task(db: Session, task: dict[str, Any], error: Exception) -> bool:
    """Force an already claimed task into a terminal state after an unexpected worker error."""

    db.rollback()
    source = Path(str(task.get("sourcePath") or ""))
    source_missing = not source.exists()
    error_code = "SOURCE_NOT_FOUND" if source_missing else "IMPORT_WORKER_FAILED"
    error_summary = (
        f"导入源已不存在：{source}"
        if source_missing
        else str(error) or error.__class__.__name__
    )
    now = _now()
    failed = fail_claimed_import_task_row(
        db,
        task,
        error_code=error_code,
        error_summary=error_summary,
        message="导入源文件或目录不存在，任务已结束" if source_missing else "导入工作进程异常，任务已结束",
        retryable=not source_missing,
        now=now,
    )
    db.commit()
    return failed


class PersistentImportWorker:
    def __init__(
        self,
        db_factory: Callable[[], Session],
        settings: Settings,
        heartbeat_db_factory: Callable[[], Session] | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self.worker_id = f"import-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="shuku-persistent-import-worker", daemon=True)
        self._heartbeat = QueueHeartbeatPump(
            heartbeat_db_factory or db_factory,
            queue_name="import",
            instance_id=self.worker_id,
            poll_interval_seconds=settings.import_queue_interval_seconds,
        )

    def start(self) -> None:
        with self.db_factory() as db:
            recovered = recover_stale_import_tasks(db)
            if recovered:
                print(f"[import-worker] recovered {recovered} stale import task(s)", flush=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def request_stop(self) -> None:
        self._stop_event.set()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def process_once(self) -> bool:
        with self.db_factory() as db:
            recovered = recover_stale_import_tasks(db)
            task = claim_next_import_task(db, self.worker_id, max(900, self.settings.ebook_conversion_timeout_seconds + 300))
            if not task:
                return bool(recovered)
            try:
                process_import_task(db, self.settings, task)
            except Exception as exc:
                fail_claimed_import_task(db, task, exc)
                print(f"[import-worker] persistent task failed {task.get('id')}: {exc}", flush=True)
            return True

    def _run(self) -> None:
        self._heartbeat.start()
        try:
            while not self._stop_event.is_set():
                error = None
                processed = False
                try:
                    processed = self.process_once()
                except Exception as exc:
                    error = exc
                self._heartbeat.pulse(processed=processed, error=error)
                if processed:
                    continue
                self._stop_event.wait(self.settings.import_queue_interval_seconds)
        finally:
            self._heartbeat.stop()


def start_persistent_import_worker(
    db_factory: Callable[[], Session],
    settings: Settings,
    heartbeat_db_factory: Callable[[], Session] | None = None,
) -> PersistentImportWorker:
    worker = PersistentImportWorker(db_factory, settings, heartbeat_db_factory)
    worker.start()
    return worker
