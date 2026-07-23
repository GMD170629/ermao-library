from __future__ import annotations

import json
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.core.config import Settings
from app.services.system_events import record_system_event
from app.services.import_preferences import (
    SUPPORTED_IMPORT_EXTENSIONS,
    load_import_preferences,
    matches_ignore_patterns,
)
from app.worker.importer import is_supported_import_file
from app.services.audio_metadata import audio_bundle_root, collect_audio_bundle_files, is_supported_audio_file
from app.worker.persistent_import_queue import enqueue_import_task
from app.worker.path_security import PathSecurityService

RESCAN_REQUESTED_AT_KEY = "monitor.rescanRequestedAt"
RESCAN_HANDLED_AT_KEY = "monitor.rescanHandledAt"


@dataclass(frozen=True)
class MonitorFolderConfig:
    id: str
    root_path: str
    shelf_id: str | None = None
    ignore_hidden: bool = True
    ignore_patterns: str | None = None
    min_file_size_bytes: int = 10240
    global_ignore_patterns: str = ""
    allowed_extensions: tuple[str, ...] = SUPPORTED_IMPORT_EXTENSIONS
    stability_check_enabled: bool = True
    stability_check_seconds: float = 2.0
    auto_convert_to_epub: bool = True


class ImportQueueProtocol(Protocol):
    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None: ...


@dataclass
class WatchState:
    observer: Observer
    root_path: Path
    config_signature: str
    timers: dict[Path, threading.Timer] = field(default_factory=dict)


@dataclass
class ScanSummary:
    directories_scanned: int = 0
    files_scanned: int = 0
    candidates_found: int = 0
    cached_files: int = 0
    ignored_files: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)


class ImportQueue:
    def __init__(self, db_factory, settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self._queue: queue.Queue[tuple[Path, MonitorFolderConfig] | None] = queue.Queue()
        self._queued_paths: set[Path] = set()
        self._known_paths: set[Path] = set()
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="shuku-import-queue", daemon=True)
        self._thread.start()

    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None:
        real = path.resolve()
        with self._lock:
            # A directory-backed audiobook is a mutable bundle: adding a new
            # episode must be allowed to enqueue the directory again. Rescans
            # suppress unchanged bundles before they reach this queue.
            if (real in self._known_paths and real.is_file()) or real in self._queued_paths:
                return
            self._queued_paths.add(real)
        self._queue.put((real, folder))

    def reload_known_paths(self, db: Session) -> None:
        known_paths = load_known_import_paths(db)
        with self._lock:
            self._known_paths = known_paths

    def stop(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, folder = item
            try:
                with self.db_factory() as db:
                    if import_watched_file(db, self.settings, path, folder):
                        with self._lock:
                            self._known_paths.add(path)
            except Exception as exc:
                print(f"[import-worker] watched import failed {path}: {exc}", flush=True)
            finally:
                with self._lock:
                    self._queued_paths.discard(path)
                self._queue.task_done()


class WorkerFileHandler(FileSystemEventHandler):
    def __init__(self, manager: "WorkerManager", folder: MonitorFolderConfig, state: WatchState) -> None:
        self.manager = manager
        self.folder = folder
        self.state = state

    def on_created(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._schedule(event)

    def on_moved(self, event: FileMovedEvent) -> None:
        if not event.is_directory:
            self.manager.schedule_import(Path(event.dest_path), self.folder, self.state)

    def _schedule(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self.manager.schedule_import(Path(event.src_path), self.folder, self.state)


class WorkerManager:
    def __init__(self, db_factory, settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self.security = PathSecurityService(settings)
        self.watchers: dict[str, WatchState] = {}
        self.import_queue = ImportQueue(db_factory, settings)
        self.last_handled_rescan_request: str | None = None

    def refresh_worker_state(self) -> None:
        with self.db_factory() as db:
            self.import_queue.reload_known_paths(db)
            self.refresh_watchers(db)
            self.process_rescan_requests(db)

    def refresh_watchers(self, db: Session) -> None:
        folders = enabled_monitor_folders(db)
        active_ids = {folder.id for folder in folders}
        for folder_id, state in list(self.watchers.items()):
            folder = next((item for item in folders if item.id == folder_id), None)
            if folder_id not in active_ids or (folder and state.config_signature != config_signature(folder)):
                self._stop_watcher(folder_id)

        for folder in folders:
            if folder.id in self.watchers:
                continue
            try:
                real_path = self.security.validate_monitor_folder(folder.root_path).real_path
            except Exception as exc:
                print(f"[import-worker] monitor folder unavailable {folder.root_path}: {exc}", flush=True)
                record_system_event(
                    db,
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="monitorFolder",
                    target_id=folder.id,
                    message=f"监控文件夹扫描失败：{folder.root_path}",
                    metadata={"rootPath": folder.root_path, "trigger": "watcher_started", "error": str(exc)},
                    commit=True,
                    prune=True,
                )
                continue
            observer = Observer()
            state = WatchState(observer=observer, root_path=real_path, config_signature=config_signature(folder))
            observer.schedule(WorkerFileHandler(self, folder, state), str(real_path), recursive=True)
            observer.start()
            self.watchers[folder.id] = state
            print(f"[import-worker] monitoring {real_path}", flush=True)
            scan_directory_with_logging(db, real_path, folder, self.import_queue, trigger="watcher_started")

    def process_rescan_requests(self, db: Session) -> None:
        try:
            settings = {row["key"]: row["value"] for row in db.execute(text("SELECT `key`, `value` FROM `SystemSetting` WHERE `key` IN (:requested, :handled)"), {"requested": RESCAN_REQUESTED_AT_KEY, "handled": RESCAN_HANDLED_AT_KEY}).mappings()}
        except SQLAlchemyError as exc:
            print(f"[import-worker] system settings unavailable, retrying later: {exc}", flush=True)
            return
        requested_at = settings.get(RESCAN_REQUESTED_AT_KEY)
        handled_at = settings.get(RESCAN_HANDLED_AT_KEY)
        if not requested_at or requested_at == handled_at or requested_at == self.last_handled_rescan_request:
            return
        request_timestamp = requested_at
        requested_folder_ids: set[str] | None = None
        try:
            request_payload = json.loads(requested_at)
        except (TypeError, ValueError, json.JSONDecodeError):
            request_payload = None
        if isinstance(request_payload, dict):
            request_timestamp = str(request_payload.get("requestedAt") or requested_at)
            raw_folder_ids = request_payload.get("monitorFolderIds")
            if isinstance(raw_folder_ids, list):
                requested_folder_ids = {
                    str(folder_id)
                    for folder_id in raw_folder_ids
                    if str(folder_id).strip()
                }
        print(f"[import-worker] rescan requested at {request_timestamp}", flush=True)
        folders = enabled_monitor_folders(db)
        if requested_folder_ids is not None:
            folders = [folder for folder in folders if folder.id in requested_folder_ids]
        record_system_event(
            db,
            source="import",
            action="rescan.started",
            target_type="monitorFolder",
            message=f"开始重新扫描 {len(folders)} 个监控文件夹",
            metadata={"requestedAt": request_timestamp, "folderCount": len(folders)},
            commit=True,
        )
        completed_folders = 0
        for folder in folders:
            try:
                real_path = self.security.validate_monitor_folder(folder.root_path).real_path
            except Exception as exc:
                print(f"[import-worker] rescan monitor folder unavailable {folder.root_path}: {exc}", flush=True)
                record_system_event(
                    db,
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="monitorFolder",
                    target_id=folder.id,
                    message=f"监控文件夹重新扫描失败：{folder.root_path}",
                    metadata={"rootPath": folder.root_path, "trigger": "manual_rescan", "requestedAt": request_timestamp, "error": str(exc)},
                    commit=True,
                    prune=True,
                )
                continue
            scan_directory_with_logging(db, real_path, folder, self.import_queue, trigger="manual_rescan", requested_at=request_timestamp)
            completed_folders += 1
        self.last_handled_rescan_request = requested_at
        upsert_system_setting(db, RESCAN_HANDLED_AT_KEY, requested_at)
        record_system_event(
            db,
            source="import",
            action="rescan.completed",
            level="warning" if completed_folders != len(folders) else "info",
            target_type="monitorFolder",
            message=f"重新扫描完成：{completed_folders}/{len(folders)} 个监控文件夹",
            metadata={"requestedAt": request_timestamp, "folderCount": len(folders), "completedFolderCount": completed_folders},
            commit=True,
            prune=True,
        )

    def schedule_import(self, path: Path, folder: MonitorFolderConfig, state: WatchState) -> None:
        if should_ignore_file(path, folder):
            return
        candidate = path
        if is_supported_audio_file(path):
            possible_root = audio_bundle_root(path, state.root_path)
            candidate = (
                possible_root
                if possible_root.is_dir()
                and possible_root.resolve() != state.root_path.resolve()
                and _is_proven_audio_bundle_directory(possible_root)
                else path
            )
        if candidate.is_dir():
            # A second track can turn an earlier single-file event into a
            # proven bundle. Cancel its pending child timer so only one task is
            # eventually enqueued.
            for pending_path, pending_timer in list(state.timers.items()):
                try:
                    pending_path.resolve().relative_to(candidate.resolve())
                except ValueError:
                    continue
                pending_timer.cancel()
                state.timers.pop(pending_path, None)
        else:
            for pending_path in state.timers:
                if not pending_path.is_dir():
                    continue
                try:
                    candidate.resolve().relative_to(pending_path.resolve())
                except ValueError:
                    continue
                return
        existing = state.timers.pop(candidate, None)
        if existing:
            existing.cancel()
        # File-system events are briefly debounced here; the configurable
        # stability window is applied once, immediately before enqueueing.
        timer = threading.Timer(0.25, lambda: self.import_queue.enqueue(candidate, folder))
        state.timers[candidate] = timer
        timer.start()

    def shutdown(self) -> None:
        for folder_id in list(self.watchers):
            self._stop_watcher(folder_id)
        self.import_queue.stop()

    def _stop_watcher(self, folder_id: str) -> None:
        state = self.watchers.pop(folder_id, None)
        if not state:
            return
        for timer in state.timers.values():
            timer.cancel()
        state.observer.stop()
        state.observer.join(timeout=10)
        print(f"[import-worker] stopped monitor {state.root_path}", flush=True)


def enabled_monitor_folders(db: Session) -> list[MonitorFolderConfig]:
    try:
        rows = db.execute(text("SELECT * FROM `MonitorFolder` WHERE `enabled` = 1 ORDER BY `createdAt` DESC")).mappings().all()
    except SQLAlchemyError as exc:
        print(f"[import-worker] monitor folders unavailable, retrying later: {exc}", flush=True)
        return []
    preferences = load_import_preferences(db)
    return [
            MonitorFolderConfig(
                id=row["id"],
                root_path=row["rootPath"],
                shelf_id=row.get("shelfId"),
                ignore_hidden=bool(row.get("ignoreHidden", True)),
                ignore_patterns=row.get("ignorePatterns"),
                min_file_size_bytes=int(row.get("minFileSizeBytes") or 10240),
                global_ignore_patterns=preferences.ignore_patterns,
                allowed_extensions=preferences.allowed_extensions,
                stability_check_enabled=preferences.stability_check_enabled,
                stability_check_seconds=preferences.stability_check_seconds,
                auto_convert_to_epub=preferences.auto_convert_to_epub,
        )
        for row in rows
    ]


def should_ignore_path(path: Path, folder: MonitorFolderConfig) -> bool:
    if any(part.endswith(".part") or part.startswith(".upload-") for part in path.parts):
        return True
    if folder.ignore_hidden and any(part.startswith(".") and len(part) > 1 for part in path.parts):
        return True
    return matches_ignore_patterns(path, folder.global_ignore_patterns) or matches_ignore_patterns(path, folder.ignore_patterns)


def should_ignore_file(path: Path, folder: MonitorFolderConfig) -> bool:
    if should_ignore_path(path, folder) or not is_supported_import_file(path):
        return True
    if path.suffix and path.suffix.lower() not in folder.allowed_extensions:
        return True
    return False


def config_signature(folder: MonitorFolderConfig) -> str:
    return "|".join([
        folder.root_path,
        folder.shelf_id or "",
        str(folder.ignore_hidden),
        folder.ignore_patterns or "",
        str(folder.min_file_size_bytes),
        folder.global_ignore_patterns,
        ",".join(folder.allowed_extensions),
        str(folder.stability_check_enabled),
        str(folder.stability_check_seconds),
        str(folder.auto_convert_to_epub),
    ])


_TRACK_FILE_PATTERN = re.compile(
    r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:(?:track|chapter|chap|ch|第)\s*)?[\[(]?\d{1,6}[\])]?(?:\s*[章回集节])?(?:[ ._-]+|$)",
    re.I,
)
_EPISODE_FILE_PATTERN = re.compile(r"第\s*\d{1,6}\s*[章回集节]", re.I)


def _is_proven_audio_bundle_directory(path: Path, files: list[Path] | None = None) -> bool:
    """Apply directory-first audiobook grouping below a monitor root.

    A user-created directory is the strongest grouping boundary. Track
    numbers can occur after a book title (for example ``《书名》第153集``),
    so filename-prefix heuristics must not split such a directory into one
    edition per file. A mixed directory that also contains another supported
    book format remains conservative and keeps its audio files independent.
    """

    try:
        candidates = files if files is not None else collect_audio_bundle_files(path)
    except (OSError, ValueError):
        return False
    if len(candidates) < 2:
        return False
    try:
        has_sibling_book = any(
            child.is_file()
            and not is_supported_audio_file(child)
            and is_supported_import_file(child)
            for child in path.iterdir()
        )
    except OSError:
        return False
    if not has_sibling_book:
        return True
    # In a mixed-media folder, retain the older explicit-prefix safeguard so
    # a split audiobook plus its PDF appendix still imports as two media items.
    return all(_TRACK_FILE_PATTERN.match(item.name) or _EPISODE_FILE_PATTERN.search(item.stem) for item in candidates)


def _audio_bundle_is_fully_imported(db: Session, path: Path) -> bool:
    try:
        files = collect_audio_bundle_files(path)
    except (OSError, ValueError):
        return False
    if not files:
        return False
    params = {f"path_{index}": str(item.resolve()) for index, item in enumerate(files)}
    placeholders = ", ".join(f":path_{index}" for index in range(len(files)))
    try:
        rows = db.execute(
            text(
                "SELECT file.`editionId` FROM `LibraryFile` file "
                "JOIN `LibraryEdition` edition ON edition.`id` = file.`editionId` "
                f"WHERE file.`path` IN ({placeholders}) AND COALESCE(edition.`hidden`, 0) = 0"
            ),
            params,
        ).mappings().all()
    except SQLAlchemyError:
        return False
    return len(rows) == len(files) and len({str(row.get("editionId") or "") for row in rows}) == 1


def wait_for_stable_file(path: Path, min_file_size_bytes: int, delay_seconds: float = 2.0) -> bool:
    try:
        before = path.stat()
    except OSError:
        return False
    if not path.is_file() or before.st_size < min_file_size_bytes:
        return False
    time.sleep(delay_seconds)
    try:
        after = path.stat()
    except OSError:
        return False
    return after.st_size == before.st_size and after.st_mtime_ns == before.st_mtime_ns


def wait_for_stable_import_source(path: Path, min_file_size_bytes: int, delay_seconds: float = 2.0) -> bool:
    if path.is_file():
        return wait_for_stable_file(path, min_file_size_bytes, delay_seconds)
    files = collect_audio_bundle_files(path)
    if not files:
        return False
    before: list[tuple[Path, int, int]] = []
    try:
        for item in files:
            stat = item.stat()
            if stat.st_size < min_file_size_bytes:
                return False
            before.append((item, stat.st_size, stat.st_mtime_ns))
    except OSError:
        return False
    time.sleep(delay_seconds)
    try:
        after_files = collect_audio_bundle_files(path)
        if after_files != files:
            return False
        return all(item.stat().st_size == size and item.stat().st_mtime_ns == mtime for item, size, mtime in before)
    except OSError:
        return False


def _add_work_to_target_shelf(db: Session, folder: MonitorFolderConfig, work_id: str | None) -> None:
    if not folder.shelf_id or not work_id:
        return
    shelf = db.execute(text("SELECT `id` FROM `Shelf` WHERE `id` = :shelf_id"), {"shelf_id": folder.shelf_id}).mappings().first()
    if not shelf:
        return
    db.execute(
        text("INSERT OR IGNORE INTO `ShelfWork` (`shelfId`, `workId`, `createdAt`) VALUES (:shelf_id, :work_id, CURRENT_TIMESTAMP)"),
        {"shelf_id": folder.shelf_id, "work_id": work_id},
    )
    db.execute(text("UPDATE `Shelf` SET `updatedAt` = CURRENT_TIMESTAMP WHERE `id` = :shelf_id"), {"shelf_id": folder.shelf_id})
    db.commit()


def import_watched_file(db: Session, settings: Settings, path: Path, folder: MonitorFolderConfig) -> bool:
    if should_ignore_file(path, folder) and path.is_file():
        return False
    delay = folder.stability_check_seconds
    stable = (
        wait_for_stable_import_source(path, folder.min_file_size_bytes, delay)
        if folder.stability_check_enabled
        else import_source_meets_minimum_size(path, folder.min_file_size_bytes)
    )
    if not stable:
        record_system_event(
            db,
            source="import",
            action="scan.file.deferred",
            level="warning",
            target_type="monitorFolder",
            target_id=folder.id,
            message=f"扫描到的文件尚未稳定，暂缓导入：{path.name}",
            metadata={
                "sourcePath": str(path),
                "monitorFolderId": folder.id,
                "minFileSizeBytes": folder.min_file_size_bytes,
                "stabilityCheckEnabled": folder.stability_check_enabled,
                "stabilityCheckSeconds": delay,
            },
            commit=True,
            prune=True,
        )
        return False
    existing = db.execute(
        text("SELECT `id`, `workId` FROM `ImportTask` WHERE `sourcePath` = :source_path AND `status` = 'COMPLETED' LIMIT 1"),
        {"source_path": str(path)},
    ).mappings().first()
    if existing and (path.is_file() or _audio_bundle_is_fully_imported(db, path)):
        _add_work_to_target_shelf(db, folder, existing.get("workId"))
        print(f"[import-worker] skipped already imported file {path}", flush=True)
        record_system_event(
            db,
            source="import",
            action="import.skipped",
            target_type="importTask",
            target_id=str(existing["id"]),
            message=f"扫描文件已导入，跳过处理：{path.name}",
            metadata={"sourcePath": str(path), "monitorFolderId": folder.id, "reason": "completed_import_task_exists"},
            commit=True,
            prune=True,
        )
        return True
    enqueue_import_task(
        db,
        path,
        origin="WATCH",
        original_name=path.name,
        monitor_folder_id=folder.id,
        message="监控文件已进入导入队列",
        allow_terminal_requeue=path.is_dir(),
    )
    return True


def import_source_meets_minimum_size(path: Path, min_file_size_bytes: int) -> bool:
    try:
        if path.is_file():
            return path.stat().st_size >= min_file_size_bytes
        files = collect_audio_bundle_files(path)
        return bool(files) and all(item.stat().st_size >= min_file_size_bytes for item in files)
    except (OSError, ValueError):
        return False


def load_known_import_paths(db: Session) -> set[Path]:
    try:
        task_columns = {column["name"] for column in inspect(db.connection()).get_columns("ImportTask")}
        task_kind_select = ", `taskKind`" if "taskKind" in task_columns else ""
        task_rows = db.execute(
            text(f"SELECT `sourcePath`{task_kind_select} FROM `ImportTask` WHERE `sourcePath` IS NOT NULL")
        ).mappings().all()
        rows: list[str] = []
        for task in task_rows:
            candidate = Path(str(task["sourcePath"])).expanduser().resolve()
            directory_task = str(task.get("taskKind") or "").upper() == "AUDIO_BUNDLE"
            if directory_task and candidate.is_dir() and not _audio_bundle_is_fully_imported(db, candidate):
                # A failed/legacy directory task must not mask files that are
                # still spread across multiple editions.
                continue
            rows.append(str(candidate))
        if "LibraryFile" in inspect(db.connection()).get_table_names():
            rows.extend(str(value) for value in db.execute(text("SELECT `path` FROM `LibraryFile` WHERE `path` IS NOT NULL")).scalars())
    except SQLAlchemyError as exc:
        print(f"[import-worker] import task cache unavailable, retrying later: {exc}", flush=True)
        return set()
    return {Path(source_path).expanduser().resolve() for source_path in rows if source_path}


def scan_directory_for_imports(
    root_path: Path,
    folder: MonitorFolderConfig,
    import_queue: ImportQueueProtocol,
    *,
    summary: ScanSummary | None = None,
    known_paths: set[Path] | None = None,
    _scan_root: Path | None = None,
) -> ScanSummary:
    summary = summary or ScanSummary()
    scan_root = (_scan_root or root_path).resolve()
    summary.directories_scanned += 1
    try:
        bundle_files = collect_audio_bundle_files(root_path)
    except ValueError as exc:
        summary.errors.append({"path": str(root_path), "error": str(exc)})
        return summary
    is_bundle = (
        bool(bundle_files)
        and root_path.resolve() != scan_root
        and _is_proven_audio_bundle_directory(root_path, bundle_files)
    )
    handled_bundle_files: set[Path] = set()
    if is_bundle:
        summary.files_scanned += len(bundle_files)
        resolved_root = root_path.resolve()
        handled_bundle_files = {item.resolve() for item in bundle_files}
        if should_ignore_path(root_path, folder):
            summary.ignored_files += len(bundle_files)
        elif known_paths is not None and resolved_root in known_paths and handled_bundle_files.issubset(known_paths):
            summary.cached_files += len(bundle_files)
        else:
            summary.candidates_found += 1
            import_queue.enqueue(root_path, folder)
    try:
        entries = list(root_path.iterdir())
    except OSError as exc:
        print(f"[import-worker] rescan directory failed {root_path}: {exc}", flush=True)
        summary.errors.append({"path": str(root_path), "error": str(exc)})
        return summary
    for entry in entries:
        try:
            if entry.is_dir():
                if is_bundle and any(entry.resolve() in item.parents for item in handled_bundle_files):
                    # CD/Disc child tracks are represented by the parent bundle.
                    continue
                if not should_ignore_path(entry, folder):
                    scan_directory_for_imports(entry, folder, import_queue, summary=summary, known_paths=known_paths, _scan_root=scan_root)
                continue
            if not entry.is_file():
                continue
            if entry.resolve() in handled_bundle_files:
                continue
            summary.files_scanned += 1
            if should_ignore_file(entry, folder):
                summary.ignored_files += 1
                continue
            if known_paths is not None and entry.resolve() in known_paths:
                summary.cached_files += 1
                continue
            summary.candidates_found += 1
            import_queue.enqueue(entry, folder)
        except OSError as exc:
            summary.errors.append({"path": str(entry), "error": str(exc)})
    return summary


def scan_directory_with_logging(
    db: Session,
    root_path: Path,
    folder: MonitorFolderConfig,
    import_queue: ImportQueueProtocol,
    *,
    trigger: str,
    requested_at: str | None = None,
) -> ScanSummary:
    base_metadata = {
        "rootPath": str(root_path),
        "monitorFolderId": folder.id,
        "trigger": trigger,
        "requestedAt": requested_at,
    }
    record_system_event(
        db,
        source="import",
        action="scan.started",
        target_type="monitorFolder",
        target_id=folder.id,
        message=f"开始扫描监控文件夹：{root_path.name or root_path}",
        metadata=base_metadata,
        commit=True,
    )

    candidates: list[tuple[Path, MonitorFolderConfig]] = []

    class StagedImportQueue:
        def enqueue(self, path: Path, queued_folder: MonitorFolderConfig) -> None:
            candidates.append((path, queued_folder))

    known_paths = load_known_import_paths(db)
    summary = scan_directory_for_imports(root_path, folder, StagedImportQueue(), known_paths=known_paths)
    for index, (path, _queued_folder) in enumerate(candidates, start=1):
        flush_batch = index % 100 == 0
        record_system_event(
            db,
            source="import",
            action="scan.file.detected",
            target_type="monitorFolder",
            target_id=folder.id,
            message=f"扫描到可导入文件：{path.name}",
            metadata={**base_metadata, "sourcePath": str(path), "format": path.suffix.lower().removeprefix(".")},
            commit=flush_batch,
            prune=flush_batch,
        )
    error_count = len(summary.errors)
    action = "scan.completed_with_errors" if error_count else "scan.completed"
    record_system_event(
        db,
        source="import",
        action=action,
        level="warning" if error_count else "info",
        target_type="monitorFolder",
        target_id=folder.id,
        message=(
            f"扫描完成：检查 {summary.files_scanned} 个文件，发现 {summary.candidates_found} 个新增待识别文件"
            + (f"，跳过 {summary.cached_files} 个已有扫描记录" if summary.cached_files else "")
            + (f"，{error_count} 个目录或文件读取失败" if error_count else "")
        ),
        metadata={
            **base_metadata,
            "directoriesScanned": summary.directories_scanned,
            "filesScanned": summary.files_scanned,
            "candidatesFound": summary.candidates_found,
            "cachedFiles": summary.cached_files,
            "ignoredFiles": summary.ignored_files,
            "errors": summary.errors[:20],
            "errorCount": error_count,
        },
        prune=True,
    )
    db.commit()
    for path, queued_folder in candidates:
        import_queue.enqueue(path, queued_folder)
    return summary


def upsert_system_setting(db: Session, key: str, value: str) -> None:
    existing = db.execute(text("SELECT `key` FROM `SystemSetting` WHERE `key` = :key"), {"key": key}).first()
    if existing:
        db.execute(text("UPDATE `SystemSetting` SET `value` = :value WHERE `key` = :key"), {"key": key, "value": value})
    else:
        db.execute(text("INSERT INTO `SystemSetting` (`key`, `value`, `createdAt`, `updatedAt`) VALUES (:key, :value, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"), {"key": key, "value": value})
    db.commit()
