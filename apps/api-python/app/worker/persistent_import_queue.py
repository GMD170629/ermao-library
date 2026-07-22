from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.worker.importer import ImportOptions, ImportResult, import_managed_book
from app.services.audio_metadata import collect_audio_bundle_files


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _id() -> str:
    return f"py_{time.time_ns()}"


def _has_table(db: Session, table: str) -> bool:
    return table in inspect(db.connection()).get_table_names()


def _columns(db: Session, table: str) -> set[str]:
    return {column["name"] for column in inspect(db.connection()).get_columns(table)}


def _row(db: Session, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = db.execute(text(sql), params).mappings().first()
    return dict(result) if result else None


def enqueue_import_task(
    db: Session,
    source_path: str | Path,
    *,
    origin: str,
    original_name: str | None = None,
    requested_title: str | None = None,
    requested_author: str | None = None,
    monitor_folder_id: str | None = None,
    message: str = "等待后台处理",
    allow_terminal_requeue: bool = False,
) -> tuple[dict[str, Any], bool]:
    source = Path(source_path).expanduser().resolve()
    existing_statuses = "'PENDING', 'PARSING'" if allow_terminal_requeue else "'PENDING', 'PARSING', 'COMPLETED', 'FAILED'"
    existing = _row(
        db,
        f"SELECT * FROM `ImportTask` WHERE `sourcePath` = :source_path AND `status` IN ({existing_statuses}) ORDER BY `createdAt` DESC LIMIT 1",
        {"source_path": str(source)},
    )
    if existing:
        return existing, False
    now = _now()
    bundle_files = collect_audio_bundle_files(source)
    is_audio_bundle = source.is_dir() and bool(bundle_files)
    values: dict[str, Any] = {
        "id": _id(),
        "monitorFolderId": monitor_folder_id,
        "origin": origin,
        "status": "PENDING",
        "originalName": original_name or source.name,
        "requestedTitle": requested_title,
        "requestedAuthor": requested_author,
        "sourcePath": str(source),
        "taskKind": "AUDIO_BUNDLE" if is_audio_bundle else "FILE",
        "bundleKey": str(source) if is_audio_bundle else None,
        "assetCount": len(bundle_files) if is_audio_bundle else 1,
        "processedAssetCount": 0,
        "progress": 0,
        "duplicate": False,
        "duration": 0,
        "errorCode": None,
        "retryable": False,
        "attempts": 0,
        "message": message,
        "createdAt": now,
        "updatedAt": now,
    }
    columns = _columns(db, "ImportTask")
    values = {key: value for key, value in values.items() if key in columns}
    keys = ", ".join(f"`{key}`" for key in values)
    params = ", ".join(f":{key}" for key in values)
    db.execute(text(f"INSERT INTO `ImportTask` ({keys}) VALUES ({params})"), values)
    if is_audio_bundle and _has_table(db, "ImportAsset"):
        asset_columns = _columns(db, "ImportAsset")
        for index, asset_path in enumerate(bundle_files):
            asset_values: dict[str, Any] = {
                "id": _id(),
                "importTaskId": values["id"],
                "sourcePath": str(asset_path),
                "status": "PENDING",
                "sortOrder": index,
                "createdAt": now,
                "updatedAt": now,
            }
            asset_values = {key: value for key, value in asset_values.items() if key in asset_columns}
            asset_keys = ", ".join(f"`{key}`" for key in asset_values)
            asset_params = ", ".join(f":{key}" for key in asset_values)
            db.execute(text(f"INSERT INTO `ImportAsset` ({asset_keys}) VALUES ({asset_params})"), asset_values)
    db.commit()
    return _row(db, "SELECT * FROM `ImportTask` WHERE `id` = :id", {"id": values["id"]}) or values, True


def recover_stale_import_tasks(db: Session) -> int:
    if not _has_table(db, "ImportTask"):
        return 0
    columns = _columns(db, "ImportTask")
    if "leaseExpiresAt" not in columns:
        return 0
    now = _now()
    result = db.execute(
        text(
            "UPDATE `ImportTask` SET `status` = 'PENDING', `progress` = 0, `message` = '后台任务恢复后重新排队', "
            "`leaseOwner` = NULL, `leaseExpiresAt` = NULL, `updatedAt` = :now "
            "WHERE `status` = 'PARSING' AND (`leaseExpiresAt` IS NULL OR `leaseExpiresAt` < :now)"
        ),
        {"now": now},
    )
    db.commit()
    return int(result.rowcount or 0)


def claim_next_import_task(db: Session, worker_id: str, lease_seconds: int) -> dict[str, Any] | None:
    if not _has_table(db, "ImportTask"):
        return None
    columns = _columns(db, "ImportTask")
    now = datetime.now()
    lease_expires = (now + timedelta(seconds=lease_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    if {"leaseOwner", "leaseExpiresAt", "attempts"}.issubset(columns):
        result = db.execute(
            text(
                "UPDATE `ImportTask` SET `status` = 'PARSING', `leaseOwner` = :worker_id, `leaseExpiresAt` = :lease_expires, "
                "`attempts` = COALESCE(`attempts`, 0) + 1, `message` = '正在准备导入', `updatedAt` = :now "
                "WHERE `id` = (SELECT `id` FROM `ImportTask` WHERE `status` = 'PENDING' ORDER BY `createdAt` ASC LIMIT 1) "
                "AND `status` = 'PENDING'"
            ),
            {"worker_id": worker_id, "lease_expires": lease_expires, "now": now.strftime("%Y-%m-%d %H:%M:%S")},
        )
        db.commit()
        if not result.rowcount:
            return None
        return _row(
            db,
            "SELECT * FROM `ImportTask` WHERE `leaseOwner` = :worker_id AND `status` = 'PARSING' ORDER BY `updatedAt` DESC LIMIT 1",
            {"worker_id": worker_id},
        )
    task = _row(db, "SELECT * FROM `ImportTask` WHERE `status` = 'PENDING' ORDER BY `createdAt` ASC LIMIT 1", {})
    if not task:
        return None
    db.execute(text("UPDATE `ImportTask` SET `status` = 'PARSING' WHERE `id` = :id"), {"id": task["id"]})
    db.commit()
    return task


def _add_work_to_shelf(db: Session, monitor_folder_id: str | None, work_id: str) -> None:
    if not monitor_folder_id or not _has_table(db, "ShelfWork") or not _has_table(db, "MonitorFolder"):
        return
    folder = _row(db, "SELECT `shelfId` FROM `MonitorFolder` WHERE `id` = :id", {"id": monitor_folder_id})
    shelf_id = (folder or {}).get("shelfId")
    if not shelf_id:
        return
    db.execute(
        text("INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :work_id, :now)"),
        {"shelf_id": shelf_id, "work_id": work_id, "now": _now()},
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
        ),
    )
    _add_work_to_shelf(db, task.get("monitorFolderId"), result.work_id)
    if _has_table(db, "DownloadTask"):
        db.execute(
            text("UPDATE `DownloadTask` SET `bookId` = :book_id, `status` = 'completed', `progress` = 100, `updatedAt` = :now WHERE `filePath` = :source_path"),
            {"book_id": result.work_id, "now": _now(), "source_path": str(task["sourcePath"])},
        )
        db.commit()
    return result


class PersistentImportWorker:
    def __init__(self, db_factory: Callable[[], Session], settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self.worker_id = f"import-{uuid.uuid4().hex}"
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="shuku-persistent-import-worker", daemon=True)

    def start(self) -> None:
        with self.db_factory() as db:
            recovered = recover_stale_import_tasks(db)
            if recovered:
                print(f"[import-worker] recovered {recovered} stale import task(s)", flush=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=10)

    def process_once(self) -> bool:
        with self.db_factory() as db:
            task = claim_next_import_task(db, self.worker_id, max(900, self.settings.ebook_conversion_timeout_seconds + 300))
            if not task:
                return False
            try:
                process_import_task(db, self.settings, task)
            except Exception as exc:
                print(f"[import-worker] persistent task failed {task.get('id')}: {exc}", flush=True)
            return True

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self.process_once():
                continue
            self._stop_event.wait(self.settings.import_queue_interval_seconds)


def start_persistent_import_worker(db_factory: Callable[[], Session], settings: Settings) -> PersistentImportWorker:
    worker = PersistentImportWorker(db_factory, settings)
    worker.start()
    return worker
