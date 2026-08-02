from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.bootstrap.imports import (
    MonitorFolderConfig,
    ScanSummary,
    StreamingDirectoryScanner,
    enqueue_import_task,
    import_file_ignore_reason,
    import_queue_at_high_watermark,
    import_source_already_known,
    import_source_meets_minimum_size,
    library_repository,
    monitor_folder_config,
    monitor_repository,
    schedule_import_scan_job,
    should_ignore_file,
)
from app.core.config import Settings
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.public import commit_import_checkpoint
from app.modules.system.public import is_database_busy_error
from app.services.audio_metadata import (
    audio_bundle_root,
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import load_import_preferences
from app.services.system_events import record_system_event
from app.worker.path_security import PathSecurityError, PathSecurityService


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
WATCHER_DATABASE_RETRY_DELAYS_SECONDS = (0.05, 0.2)


@dataclass
class WatchState:
    observer: Observer
    root_path: Path
    config_signature: str


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
            self._schedule_path(Path(event.dest_path))

    def _schedule(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._schedule_path(Path(event.src_path))

    def _schedule_path(self, path: Path) -> None:
        try:
            self.manager.schedule_import(path, self.folder, self.state)
        except Exception as exc:  # noqa: BLE001 — watchdog callback containment boundary
            print(
                f"[import-worker] watcher event scheduling failed {path.name}: {exc}",
                flush=True,
            )


class WorkerManager:
    def __init__(self, db_factory, settings: Settings) -> None:
        self.db_factory = db_factory
        self.settings = settings
        self.security = PathSecurityService()
        self.watchers: dict[str, WatchState] = {}
        self._imports_paused = False
        self._pending_scan_recovery_folder_ids: set[str] = set()
        self.last_handled_rescan_request: str | None = None

    def refresh_worker_state(self) -> None:
        with self.db_factory() as db:
            self.refresh_watchers(db)
            self.process_rescan_requests(db)
        self._schedule_pending_recovery_scans()

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
            except PathSecurityError as exc:
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
            schedule_import_scan_job(
                db,
                monitor_folder_id=folder.id,
                actor_user_id=None,
                root_path=real_path,
                trigger="watcher_started",
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
        scheduled_folders = 0
        for folder in folders:
            try:
                real_path = self.security.validate_monitor_folder(
                    folder.root_path
                ).real_path
            except PathSecurityError as exc:
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
                )
                continue
            _job, created = schedule_import_scan_job(
                db,
                monitor_folder_id=folder.id,
                actor_user_id=None,
                root_path=real_path,
                trigger="manual_rescan",
            )
            scheduled_folders += int(created)
        self.last_handled_rescan_request = requested_at
        upsert_system_setting(db, RESCAN_HANDLED_AT_KEY, requested_at)
        record_system_event(
            db,
            source="import",
            action="rescan.completed",
            level="info",
            target_type="monitorFolder",
            message=f"已提交重新扫描：{len(folders)} 个监控文件夹",
            metadata={
                "requestedAt": request_timestamp,
                "folderCount": len(folders),
                "createdJobCount": scheduled_folders,
            },
            commit=True,
        )

    def schedule_import(
        self, path: Path, folder: MonitorFolderConfig, state: WatchState
    ) -> None:
        if getattr(self, "_imports_paused", False):
            return
        ignore_reason = import_file_ignore_reason(path, folder)
        if ignore_reason is not None:
            return
        audio_scan_root = (
            audio_bundle_root(path, state.root_path)
            if is_supported_audio_file(path)
            else None
        )
        for delay_seconds in (0.0, *WATCHER_DATABASE_RETRY_DELAYS_SECONDS):
            if delay_seconds:
                time.sleep(delay_seconds)
            try:
                self._schedule_import_once(
                    path,
                    folder,
                    state,
                    audio_scan_root=audio_scan_root,
                )
            except OperationalError as exc:
                if not is_database_busy_error(exc):
                    raise
                continue
            self._pending_recovery_folders().discard(folder.id)
            return
        self._pending_recovery_folders().add(folder.id)
        print(
            "[import-worker] watcher database remained busy; "
            f"scheduled folder recovery scan {folder.id}",
            flush=True,
        )

    def _schedule_import_once(
        self,
        candidate: Path,
        folder: MonitorFolderConfig,
        state: WatchState,
        *,
        audio_scan_root: Path | None,
    ) -> None:
        with self.db_factory() as db:
            if import_queue_at_high_watermark(db):
                schedule_import_scan_job(
                    db,
                    monitor_folder_id=folder.id,
                    actor_user_id=None,
                    root_path=state.root_path,
                    trigger="WATCHER_BACKPRESSURE",
                )
                return
            available_at = (
                datetime.now(UTC)
                + timedelta(seconds=max(0, folder.stability_check_seconds))
                if folder.stability_check_enabled
                else None
            )
            if audio_scan_root is not None:
                schedule_import_scan_job(
                    db,
                    monitor_folder_id=folder.id,
                    actor_user_id=None,
                    root_path=audio_scan_root,
                    trigger="WATCHER_AUDIO_EVENT",
                    available_at=available_at,
                )
                return
            enqueue_import_task(
                db,
                candidate,
                origin="WATCH",
                original_name=candidate.name,
                monitor_folder_id=folder.id,
                message="监控文件已进入导入队列",
                allow_terminal_requeue=candidate.is_dir(),
                available_at=available_at,
            )

    def _pending_recovery_folders(self) -> set[str]:
        pending = getattr(self, "_pending_scan_recovery_folder_ids", None)
        if pending is None:
            pending = set()
            self._pending_scan_recovery_folder_ids = pending
        return pending

    def _schedule_pending_recovery_scans(self) -> None:
        pending = self._pending_recovery_folders()
        for folder_id in tuple(pending):
            state = self.watchers.get(folder_id)
            if state is None:
                pending.discard(folder_id)
                continue
            try:
                with self.db_factory() as db:
                    schedule_import_scan_job(
                        db,
                        monitor_folder_id=folder_id,
                        actor_user_id=None,
                        root_path=state.root_path,
                        trigger="WATCHER_RECOVERY",
                    )
            except SQLAlchemyError as exc:
                print(
                    "[import-worker] watcher recovery scan scheduling deferred "
                    f"{folder_id}: {exc}",
                    flush=True,
                )
                continue
            pending.discard(folder_id)

    def shutdown(self) -> None:
        for folder_id in list(self.watchers):
            self._stop_watcher(folder_id)

    def pause_import_scheduling(self) -> None:
        self._imports_paused = True

    def resume_import_scheduling(self) -> None:
        self._imports_paused = False

    def _stop_watcher(self, folder_id: str) -> None:
        state = self.watchers.pop(folder_id, None)
        if not state:
            return
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
    except (AudioTrackLimitExceededError, OSError, ValueError):
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
    try:
        files = collect_audio_bundle_files(path)
    except AudioTrackLimitExceededError:
        return False
    if not files:
        return False
    before: list[tuple[Path, int, int]] = []
    try:
        for item in files:
            stat = item.stat()
            if stat.st_size < min_file_size_bytes:
                return False
            before.append((item, stat.st_size, stat.st_mtime_ns))
    except (AudioTrackLimitExceededError, OSError):
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

    summary = ScanSummary()
    ignored_reason_counts: dict[str, int] = {}
    scanner = StreamingDirectoryScanner(root_path, folder)
    try:
        while True:
            scan_slice = scanner.next_slice()
            summary.directories_scanned += scan_slice.directories_scanned
            summary.files_scanned += scan_slice.files_scanned
            summary.candidates_found += scan_slice.candidates_found
            summary.ignored_files += scan_slice.skipped_count
            summary.errors.extend(error.to_storage() for error in scan_slice.errors)
            for reason, count in scan_slice.ignored_reason_counts.items():
                ignored_reason_counts[reason] = (
                    ignored_reason_counts.get(reason, 0) + count
                )
            for path in scan_slice.candidates:
                if path.is_file() and import_source_already_known(db, path):
                    summary.cached_files += 1
                    continue
                import_queue.enqueue(path, folder)
            if scan_slice.completed:
                break
    finally:
        scanner.close()
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
            "ignoredReasonCounts": ignored_reason_counts,
            "errors": summary.errors[:20],
            "errorCount": error_count,
        },
    )
    commit_import_checkpoint(db)
    return summary
