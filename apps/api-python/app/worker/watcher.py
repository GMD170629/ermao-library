from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session
from watchdog.events import FileMovedEvent, FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from app.bootstrap.imports import (
    LibraryConfig,
    ScanSummary,
    StreamingDirectoryScanner,
    import_file_ignore_reason,
    import_queue_at_high_watermark,
    import_source_already_known,
    import_source_meets_minimum_size,
    library_repository,
    load_import_enqueue_command_projection,
    library_config,
    monitor_repository,
    persist_import_enqueue_write,
    persist_import_events,
    persist_import_rescan_completion,
    persist_import_scan_requests,
    prepare_import_enqueue_command,
    prepare_import_enqueue_write,
    should_ignore_file,
)
from app.core.config import Settings
from app.models.common import db_timestamp
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.application.scan_jobs import prepare_import_scan_job
from app.modules.system.public import PreparedSystemEvent, is_database_busy_error
from app.services.audio_metadata import (
    audio_bundle_root,
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import (
    DEFAULT_STABILITY_CHECK_ENABLED,
    IMPORT_ALLOWED_EXTENSIONS_KEY,
    IMPORT_IGNORE_PATTERNS_KEY,
    IMPORT_PREFERENCE_KEYS,
    IMPORT_STABILITY_ENABLED_KEY,
    IMPORT_STABILITY_SECONDS_KEY,
    ImportPreferences,
    default_stability_seconds,
    normalize_allowed_extensions,
    normalize_ignore_patterns,
    normalize_import_setting_value,
    normalize_stability_seconds,
)
from app.services.system_events import (
    prepare_system_event,
)
from app.worker.path_security import PathSecurityError, PathSecurityService


class ImportQueueProtocol(Protocol):
    """Queue contract owned by the watcher process boundary."""

    def enqueue(self, path: Path, folder: LibraryConfig) -> None: ...


audio_bundle_fully_imported = library_repository.audio_bundle_fully_imported
get_completed_import_task_work_id = monitor_repository.get_completed_import_task_work_id
get_system_settings = monitor_repository.get_system_settings
list_enabled_libraries = monitor_repository.list_enabled_libraries

RESCAN_REQUESTED_AT_KEY = "monitor.rescanRequestedAt"
RESCAN_HANDLED_AT_KEY = "monitor.rescanHandledAt"
WATCHER_DATABASE_RETRY_DELAYS_SECONDS = (0.05, 0.2)
WORKER_REFRESH_SETTING_KEYS = tuple(
    sorted(
        {
            RESCAN_REQUESTED_AT_KEY,
            RESCAN_HANDLED_AT_KEY,
            *IMPORT_PREFERENCE_KEYS,
        }
    )
)


def _record_worker_event(
    db: Session,
    *,
    source: str,
    action: str,
    message: str,
    level: str = "info",
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    prepared_event = prepare_system_event(
        source=source,
        action=action,
        message=message,
        level=level,
        actor_type=actor_type,
        actor_id=actor_id,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
    persist_import_events(db, (prepared_event,))


@dataclass
class WatchState:
    observer: Observer
    root_path: Path
    config_signature: str


@dataclass(frozen=True, slots=True)
class WorkerRefreshProjection:
    folders: tuple[LibraryConfig, ...]
    rescan_requested_at: str | None
    rescan_handled_at: str | None


class WorkerFileHandler(FileSystemEventHandler):
    def __init__(
        self, manager: WorkerManager, folder: LibraryConfig, state: WatchState
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
        try:
            with self.db_factory() as db:
                folder_rows = tuple(list_enabled_libraries(db))
                setting_values = get_system_settings(db, WORKER_REFRESH_SETTING_KEYS)
            folders = enabled_libraries(folder_rows, setting_values)
            projection = WorkerRefreshProjection(
                folders=folders,
                rescan_requested_at=setting_values.get(RESCAN_REQUESTED_AT_KEY),
                rescan_handled_at=setting_values.get(RESCAN_HANDLED_AT_KEY),
            )
        except SQLAlchemyError as exc:
            print(
                f"[import-worker] watcher projection unavailable, retrying later: {exc}",
                flush=True,
            )
            return
        self.refresh_watchers(projection.folders)
        self.process_rescan_requests(projection)
        self._schedule_pending_recovery_scans()

    def _persist_prepared_event(self, event: PreparedSystemEvent) -> None:
        try:
            with self.db_factory() as db:
                persist_import_events(db, (event,))
        except OperationalError as exc:
            if not is_database_busy_error(exc):
                raise
            print(
                "[import-worker] event persistence deferred reason=database_busy",
                flush=True,
            )

    def _schedule_scan_request(
        self,
        *,
        library_id: str,
        root_path: Path,
        trigger: str,
        available_at: datetime | None = None,
    ) -> None:
        checkpoint_at = datetime.now(UTC)
        prepared_job = prepare_import_scan_job(
            job_id=f"scan_{uuid4().hex}",
            work_item_id=f"work_{uuid4().hex}",
            library_id=library_id,
            actor_user_id=None,
            canonical_root_path=str(root_path.expanduser().resolve()),
            trigger=trigger,
            available_at=available_at,
            created_at=checkpoint_at,
        )
        with self.db_factory() as db:
            persist_import_scan_requests(db, (prepared_job,), ())

    def refresh_watchers(self, folders: tuple[LibraryConfig, ...]) -> None:
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
                real_path = self.security.validate_library_root(
                    folder.root_path
                ).real_path
            except PathSecurityError as exc:
                print(
                    f"[import-worker] library unavailable {folder.root_path}: {exc}",
                    flush=True,
                )
                prepared_event = prepare_system_event(
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="library",
                    target_id=folder.id,
                    message=f"书库扫描失败：{folder.root_path}",
                    metadata={
                        "rootPath": folder.root_path,
                        "trigger": "watcher_started",
                        "error": str(exc),
                    },
                )
                self._persist_prepared_event(prepared_event)
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
            try:
                self._schedule_scan_request(
                    library_id=folder.id,
                    root_path=real_path,
                    trigger="watcher_started",
                )
            except OperationalError as exc:
                if not is_database_busy_error(exc):
                    raise
                self._pending_recovery_folders().add(folder.id)
                print(
                    "[import-worker] initial watcher scan deferred "
                    f"{folder.id} reason=database_busy",
                    flush=True,
                )

    def process_rescan_requests(self, projection: WorkerRefreshProjection) -> None:
        requested_at = projection.rescan_requested_at
        handled_at = projection.rescan_handled_at
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
            raw_folder_ids = request_payload.get("libraryIds")
            if isinstance(raw_folder_ids, list):
                requested_folder_ids = {
                    str(folder_id)
                    for folder_id in raw_folder_ids
                    if str(folder_id).strip()
                }
        print(f"[import-worker] rescan requested at {request_timestamp}", flush=True)
        folders = list(projection.folders)
        if requested_folder_ids is not None:
            folders = [
                folder for folder in folders if folder.id in requested_folder_ids
            ]
        checkpoint_at = datetime.now(UTC)
        prepared_scan_jobs = []
        prepared_events: list[PreparedSystemEvent] = []
        for folder in folders:
            try:
                real_path = self.security.validate_library_root(
                    folder.root_path
                ).real_path
            except PathSecurityError as exc:
                print(
                    f"[import-worker] rescan library unavailable {folder.root_path}: {exc}",
                    flush=True,
                )
                failure_event = prepare_system_event(
                    source="import",
                    action="scan.failed",
                    level="error",
                    target_type="library",
                    target_id=folder.id,
                    message=f"书库重新扫描失败：{folder.root_path}",
                    metadata={
                        "rootPath": folder.root_path,
                        "trigger": "manual_rescan",
                        "requestedAt": request_timestamp,
                        "error": str(exc),
                    },
                )
                prepared_events.append(failure_event)
                continue
            prepared_scan_jobs.append(
                prepare_import_scan_job(
                    job_id=f"scan_{uuid4().hex}",
                    work_item_id=f"work_{uuid4().hex}",
                    library_id=folder.id,
                    actor_user_id=None,
                    canonical_root_path=str(real_path),
                    trigger="manual_rescan",
                    available_at=None,
                    created_at=checkpoint_at,
                )
            )
        completed_event = prepare_system_event(
            source="import",
            action="rescan.completed",
            level="info",
            target_type="library",
            message=f"已提交重新扫描：{len(folders)} 个书库",
            metadata={
                "requestedAt": request_timestamp,
                "folderCount": len(folders),
                "scheduledFolderCount": len(prepared_scan_jobs),
            },
        )
        prepared_events.append(completed_event)
        try:
            with self.db_factory() as db:
                created_count = persist_import_rescan_completion(
                    db,
                    setting_key=RESCAN_HANDLED_AT_KEY,
                    setting_value=requested_at,
                    checkpoint_at=checkpoint_at,
                    scan_jobs=tuple(prepared_scan_jobs),
                    events=tuple(prepared_events),
                )
        except OperationalError as exc:
            if not is_database_busy_error(exc):
                raise
            print(
                "[import-worker] rescan completion deferred reason=database_busy",
                flush=True,
            )
            return
        self.last_handled_rescan_request = requested_at
        print(
            "[import-worker] rescan checkpoint persisted "
            f"folders={len(prepared_scan_jobs)} created={created_count}",
            flush=True,
        )

    def schedule_import(
        self, path: Path, folder: LibraryConfig, state: WatchState
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
        folder: LibraryConfig,
        state: WatchState,
        *,
        audio_scan_root: Path | None,
    ) -> None:
        available_at = (
            datetime.now(UTC)
            + timedelta(seconds=max(0, folder.stability_check_seconds))
            if folder.stability_check_enabled
            else None
        )
        candidate_is_directory = candidate.is_dir()
        candidate_name = candidate.name
        with self.db_factory() as db:
            at_high_watermark = import_queue_at_high_watermark(db)
        if at_high_watermark:
            self._schedule_scan_request(
                library_id=folder.id,
                root_path=state.root_path,
                trigger="WATCHER_BACKPRESSURE",
            )
            return
        if audio_scan_root is not None:
            self._schedule_scan_request(
                library_id=folder.id,
                root_path=audio_scan_root,
                trigger="WATCHER_AUDIO_EVENT",
                available_at=available_at,
            )
            return
        command = prepare_import_enqueue_command(
            candidate,
            origin="WATCH",
            original_name=candidate_name,
            library_id=folder.id,
            message="监控文件已进入导入队列",
            allow_terminal_requeue=candidate_is_directory,
        )
        with self.db_factory() as db:
            projection = load_import_enqueue_command_projection(db, command)
        prepared = prepare_import_enqueue_write(
            command,
            projection,
            available_at=available_at or datetime.now(UTC),
        )
        with self.db_factory() as db:
            persist_import_enqueue_write(db, prepared)

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
                self._schedule_scan_request(
                    library_id=folder_id,
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


def enabled_libraries(
    rows: tuple[Mapping[str, object], ...],
    setting_values: Mapping[str, str],
) -> tuple[LibraryConfig, ...]:
    """Map detached SQL projections into watcher configuration."""

    stability_enabled = normalize_import_setting_value(
        IMPORT_STABILITY_ENABLED_KEY,
        setting_values.get(IMPORT_STABILITY_ENABLED_KEY),
    )
    preferences = ImportPreferences(
        stability_check_enabled=(
            stability_enabled
            if isinstance(stability_enabled, bool)
            else DEFAULT_STABILITY_CHECK_ENABLED
        ),
        stability_check_seconds=(
            normalize_stability_seconds(setting_values[IMPORT_STABILITY_SECONDS_KEY])
            if IMPORT_STABILITY_SECONDS_KEY in setting_values
            else default_stability_seconds()
        ),
        allowed_extensions=normalize_allowed_extensions(
            setting_values.get(IMPORT_ALLOWED_EXTENSIONS_KEY)
        ),
        ignore_patterns=normalize_ignore_patterns(
            setting_values.get(IMPORT_IGNORE_PATTERNS_KEY)
        ),
    )
    return tuple(library_config(row, preferences=preferences) for row in rows)


def config_signature(folder: LibraryConfig) -> str:
    return "|".join(
        [
            folder.root_path,
            str(folder.ignore_hidden),
            folder.ignore_patterns or "",
            str(folder.min_file_size_bytes),
            folder.global_ignore_patterns,
            ",".join(folder.allowed_extensions),
            str(folder.stability_check_enabled),
            str(folder.stability_check_seconds),
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


def import_watched_file(
    db: Session,
    settings: Settings,
    path: Path,
    folder: LibraryConfig,
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
        _record_worker_event(
            db,
            source="import",
            action="scan.file.deferred",
            level="warning",
            target_type="library",
            target_id=folder.id,
            message=f"扫描到的文件尚未稳定，暂缓导入：{path.name}",
            metadata={
                "sourcePath": str(path),
                "libraryId": folder.id,
                "minFileSizeBytes": folder.min_file_size_bytes,
                "stabilityCheckEnabled": folder.stability_check_enabled,
                "stabilityCheckSeconds": delay,
                "changedDuringStabilityCheck": changed_during_check,
                "retryScheduled": retry_after_stability_check or changed_during_check,
            },
        )
        return False
    existing = get_completed_import_task_work_id(db, str(path))
    db.close()
    if existing and (path.is_file() or _audio_bundle_is_fully_imported(db, path)):
        print(f"[import-worker] skipped already imported file {path}", flush=True)
        _record_worker_event(
            db,
            source="import",
            action="import.skipped",
            target_type="importTask",
            target_id=str(existing["id"]),
            message=f"扫描文件已导入，跳过处理：{path.name}",
            metadata={
                "sourcePath": str(path),
                "libraryId": folder.id,
                "reason": "completed_import_task_exists",
            },
        )
        return True
    command = prepare_import_enqueue_command(
        path,
        origin="WATCH",
        original_name=path.name,
        library_id=folder.id,
        message="监控文件已进入导入队列",
        allow_terminal_requeue=path.is_dir(),
    )
    projection = load_import_enqueue_command_projection(db, command)
    db.close()
    prepared = prepare_import_enqueue_write(
        command,
        projection,
        available_at=datetime.now(UTC),
    )
    persist_import_enqueue_write(db, prepared)
    return True


def scan_directory_with_logging(
    db: Session,
    root_path: Path,
    folder: LibraryConfig,
    import_queue: ImportQueueProtocol,
    *,
    trigger: str,
    requested_at: str | None = None,
) -> ScanSummary:
    base_metadata = {
        "rootPath": str(root_path),
        "libraryId": folder.id,
        "trigger": trigger,
        "requestedAt": requested_at,
    }
    _record_worker_event(
        db,
        source="import",
        action="scan.started",
        target_type="library",
        target_id=folder.id,
        message=f"开始扫描书库：{root_path.name or root_path}",
        metadata=base_metadata,
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
                is_known = path.is_file() and import_source_already_known(db, path)
                db.close()
                if is_known:
                    summary.cached_files += 1
                    continue
                import_queue.enqueue(path, folder)
            if scan_slice.completed:
                break
    finally:
        scanner.close()
    error_count = len(summary.errors)
    action = "scan.completed_with_errors" if error_count else "scan.completed"
    _record_worker_event(
        db,
        source="import",
        action=action,
        level="warning" if error_count else "info",
        target_type="library",
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
    return summary
