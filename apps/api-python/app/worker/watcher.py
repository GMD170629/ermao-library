from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.bootstrap.imports import (
    MonitorFolderConfig,
    ScanSummary,
    enqueue_import_task,
    is_proven_audio_bundle_directory,
    library_repository,
    load_known_import_paths,
    monitor_folder_config,
    monitor_repository,
    scan_directory_for_imports,
    should_ignore_file,
)
from app.core.config import Settings
from app.modules.imports.public import commit_import_checkpoint
from app.services.audio_metadata import (
    audio_bundle_root,
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import load_import_preferences
from app.services.system_events import record_system_event
from app.worker.path_security import PathSecurityService


class ImportQueueProtocol(Protocol):
    """Queue contract owned by the watcher process boundary."""

    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None: ...


audio_bundle_fully_imported = library_repository.audio_bundle_fully_imported
add_work_to_target_shelf = monitor_repository.add_work_to_target_shelf
get_completed_import_task_work_id = monitor_repository.get_completed_import_task_work_id
get_system_settings = monitor_repository.get_system_settings
list_enabled_monitor_folders = monitor_repository.list_enabled_monitor_folders
upsert_system_setting = monitor_repository.upsert_system_setting

RESCAN_REQUESTED_AT_KEY = "monitor.rescanRequestedAt"
RESCAN_HANDLED_AT_KEY = "monitor.rescanHandledAt"


@dataclass
class WatchState:
    observer: Observer
    root_path: Path
    config_signature: str
    timers: dict[Path, threading.Timer] = field(default_factory=dict)


class ImportQueue:
    def __init__(self, db_factory, settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self._queue: queue.Queue[tuple[Path, MonitorFolderConfig] | None] = (
            queue.Queue()
        )
        self._queued_paths: set[Path] = set()
        self._changed_while_pending: set[Path] = set()
        self._deferred_paths: set[Path] = set()
        self._known_paths: set[Path] = set()
        self._accepting = True
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name="shuku-import-queue", daemon=True
        )
        self._thread.start()

    def enqueue(self, path: Path, folder: MonitorFolderConfig) -> None:
        real = path.resolve()
        with self._lock:
            if not self._accepting:
                return
            # A directory-backed audiobook is a mutable bundle: adding a new
            # episode must be allowed to enqueue the directory again. Rescans
            # suppress unchanged bundles before they reach this queue.
            if real in self._known_paths and real.is_file():
                return
            if real in self._queued_paths:
                self._changed_while_pending.add(real)
                return
            self._queued_paths.add(real)
        self._queue.put((real, folder))

    def reload_known_paths(self, db: Session) -> None:
        known_paths = load_known_import_paths(db)
        with self._lock:
            self._known_paths = known_paths

    def stop(self, *, require_stopped: bool = False) -> None:
        with self._lock:
            if not self._accepting and not self._thread.is_alive():
                return
            self._accepting = False
        self._queue.put(None)
        self._thread.join(timeout=10)
        if require_stopped and self._thread.is_alive():
            raise RuntimeError("import staging queue did not stop within 10 seconds")

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            path, folder = item
            with self._lock:
                self._changed_while_pending.discard(path)
                self._deferred_paths.discard(path)
            completed = False
            try:
                with self.db_factory() as db:
                    completed = import_watched_file(
                        db,
                        self.settings,
                        path,
                        folder,
                        has_changed=lambda watched_path=path: (
                            self._path_changed_while_pending(watched_path)
                        ),
                        mark_deferred=lambda watched_path=path: self._mark_deferred(
                            watched_path
                        ),
                    )
                    if completed:
                        with self._lock:
                            self._known_paths.add(path)
            except Exception as exc:
                print(
                    f"[import-worker] watched import failed {path}: {exc}", flush=True
                )
            finally:
                with self._lock:
                    retry_after_change = not completed and (
                        path in self._changed_while_pending
                        or path in self._deferred_paths
                    )
                    self._changed_while_pending.discard(path)
                    self._deferred_paths.discard(path)
                    if not retry_after_change:
                        self._queued_paths.discard(path)
                if retry_after_change:
                    self._queue.put((path, folder))
                self._queue.task_done()

    def _path_changed_while_pending(self, path: Path) -> bool:
        with self._lock:
            return path in self._changed_while_pending

    def _mark_deferred(self, path: Path) -> None:
        with self._lock:
            self._deferred_paths.add(path)


class WorkerFileHandler(FileSystemEventHandler):
    def __init__(
        self, manager: WorkerManager, folder: MonitorFolderConfig, state: WatchState
    ) -> None:
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
        self._imports_paused = False
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
            if folder_id not in active_ids or (
                folder and state.config_signature != config_signature(folder)
            ):
                self._stop_watcher(folder_id)

        for folder in folders:
            if folder.id in self.watchers:
                continue
            try:
                real_path = self.security.validate_monitor_folder(
                    folder.root_path
                ).real_path
            except Exception as exc:
                print(
                    f"[import-worker] monitor folder unavailable {folder.root_path}: {exc}",
                    flush=True,
                )
                record_system_event(
                    db,
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="monitorFolder",
                    target_id=folder.id,
                    message=f"监控文件夹扫描失败：{folder.root_path}",
                    metadata={
                        "rootPath": folder.root_path,
                        "trigger": "watcher_started",
                        "error": str(exc),
                    },
                    commit=True,
                    prune=True,
                )
                continue
            observer = Observer()
            state = WatchState(
                observer=observer,
                root_path=real_path,
                config_signature=config_signature(folder),
            )
            observer.schedule(
                WorkerFileHandler(self, folder, state), str(real_path), recursive=True
            )
            observer.start()
            self.watchers[folder.id] = state
            print(f"[import-worker] monitoring {real_path}", flush=True)
            scan_directory_with_logging(
                db, real_path, folder, self.import_queue, trigger="watcher_started"
            )

    def process_rescan_requests(self, db: Session) -> None:
        try:
            settings = get_system_settings(
                db, (RESCAN_REQUESTED_AT_KEY, RESCAN_HANDLED_AT_KEY)
            )
        except SQLAlchemyError as exc:
            print(
                f"[import-worker] system settings unavailable, retrying later: {exc}",
                flush=True,
            )
            return
        requested_at = settings.get(RESCAN_REQUESTED_AT_KEY)
        handled_at = settings.get(RESCAN_HANDLED_AT_KEY)
        if (
            not requested_at
            or requested_at == handled_at
            or requested_at == self.last_handled_rescan_request
        ):
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
            folders = [
                folder for folder in folders if folder.id in requested_folder_ids
            ]
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
                real_path = self.security.validate_monitor_folder(
                    folder.root_path
                ).real_path
            except Exception as exc:
                print(
                    f"[import-worker] rescan monitor folder unavailable {folder.root_path}: {exc}",
                    flush=True,
                )
                record_system_event(
                    db,
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="monitorFolder",
                    target_id=folder.id,
                    message=f"监控文件夹重新扫描失败：{folder.root_path}",
                    metadata={
                        "rootPath": folder.root_path,
                        "trigger": "manual_rescan",
                        "requestedAt": request_timestamp,
                        "error": str(exc),
                    },
                    commit=True,
                    prune=True,
                )
                continue
            scan_directory_with_logging(
                db,
                real_path,
                folder,
                self.import_queue,
                trigger="manual_rescan",
                requested_at=request_timestamp,
            )
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
            metadata={
                "requestedAt": request_timestamp,
                "folderCount": len(folders),
                "completedFolderCount": completed_folders,
            },
            commit=True,
            prune=True,
        )

    def schedule_import(
        self, path: Path, folder: MonitorFolderConfig, state: WatchState
    ) -> None:
        if getattr(self, "_imports_paused", False):
            return
        if should_ignore_file(path, folder):
            return
        candidate = path
        if is_supported_audio_file(path):
            possible_root = audio_bundle_root(path, state.root_path)
            candidate = (
                possible_root
                if possible_root.is_dir()
                and is_proven_audio_bundle_directory(possible_root, folder=folder)
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
        target_queue = self.import_queue
        timer = threading.Timer(
            0.25, lambda: target_queue.enqueue(candidate, folder)
        )
        state.timers[candidate] = timer
        timer.start()

    def shutdown(self) -> None:
        for folder_id in list(self.watchers):
            self._stop_watcher(folder_id)
        self.import_queue.stop()

    def pause_import_scheduling(self) -> None:
        self._imports_paused = True
        for state in self.watchers.values():
            for timer in state.timers.values():
                timer.cancel()
            state.timers.clear()
        self.import_queue.stop(require_stopped=True)

    def resume_import_scheduling(self) -> None:
        replacement = ImportQueue(self.db_factory, self.settings)
        with self.db_factory() as db:
            replacement.reload_known_paths(db)
        self.import_queue = replacement
        self._imports_paused = False

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
        rows = list_enabled_monitor_folders(db)
    except SQLAlchemyError as exc:
        print(
            f"[import-worker] monitor folders unavailable, retrying later: {exc}",
            flush=True,
        )
        return []
    preferences = load_import_preferences(db)
    return [monitor_folder_config(row, preferences=preferences) for row in rows]


def config_signature(folder: MonitorFolderConfig) -> str:
    return "|".join(
        [
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
        ]
    )


def _audio_bundle_is_fully_imported(db: Session, path: Path) -> bool:
    try:
        files = collect_audio_bundle_files(path)
    except (OSError, ValueError):
        return False
    if not files:
        return False
    try:
        return audio_bundle_fully_imported(db, [str(item.resolve()) for item in files])
    except SQLAlchemyError:
        return False


def wait_for_stable_file(
    path: Path, min_file_size_bytes: int, delay_seconds: float = 2.0
) -> bool:
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


def wait_for_stable_import_source(
    path: Path, min_file_size_bytes: int, delay_seconds: float = 2.0
) -> bool:
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
        return all(
            item.stat().st_size == size and item.stat().st_mtime_ns == mtime
            for item, size, mtime in before
        )
    except OSError:
        return False


def _add_work_to_target_shelf(
    db: Session, folder: MonitorFolderConfig, work_id: str | None
) -> None:
    if not folder.shelf_id or not work_id:
        return
    add_work_to_target_shelf(db, shelf_id=folder.shelf_id, work_id=work_id)
    commit_import_checkpoint(db)


def import_watched_file(
    db: Session,
    settings: Settings,
    path: Path,
    folder: MonitorFolderConfig,
    *,
    has_changed: Callable[[], bool] | None = None,
    mark_deferred: Callable[[], None] | None = None,
) -> bool:
    if should_ignore_file(path, folder) and path.is_file():
        return False
    delay = folder.stability_check_seconds
    stable = (
        wait_for_stable_import_source(path, folder.min_file_size_bytes, delay)
        if folder.stability_check_enabled
        else import_source_meets_minimum_size(path, folder.min_file_size_bytes)
    )
    changed_during_check = has_changed is not None and has_changed()
    retry_after_stability_check = not stable and import_source_meets_minimum_size(
        path, folder.min_file_size_bytes
    )
    if retry_after_stability_check and mark_deferred is not None:
        mark_deferred()
    if not stable or changed_during_check:
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
                "changedDuringStabilityCheck": changed_during_check,
                "retryScheduled": retry_after_stability_check or changed_during_check,
            },
            commit=True,
            prune=True,
        )
        return False
    existing = get_completed_import_task_work_id(db, str(path))
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
            metadata={
                "sourcePath": str(path),
                "monitorFolderId": folder.id,
                "reason": "completed_import_task_exists",
            },
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
        return bool(files) and all(
            item.stat().st_size >= min_file_size_bytes for item in files
        )
    except (OSError, ValueError):
        return False


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
    summary = scan_directory_for_imports(
        root_path, folder, StagedImportQueue(), known_paths=known_paths
    )
    for index, (path, _queued_folder) in enumerate(candidates, start=1):
        flush_batch = index % 100 == 0
        record_system_event(
            db,
            source="import",
            action="scan.file.detected",
            target_type="monitorFolder",
            target_id=folder.id,
            message=f"扫描到可导入文件：{path.name}",
            metadata={
                **base_metadata,
                "sourcePath": str(path),
                "format": path.suffix.lower().removeprefix("."),
            },
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
            + (
                f"，跳过 {summary.cached_files} 个已有扫描记录"
                if summary.cached_files
                else ""
            )
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
    commit_import_checkpoint(db)
    for path, queued_folder in candidates:
        import_queue.enqueue(path, queued_folder)
    return summary
