"""Imports write HTTP surface: upload, scan, delete, retry, rescan."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.bootstrap.imports import (
    MonitorFolderConfig,
    enqueue_import_task,
    import_http_store,
    load_known_import_paths,
    monitor_folder_config,
    scan_directory_for_imports,
    stage_import_task,
)
from app.bootstrap.system import record_system_event, upsert_setting
from app.core.authorization import authorization_context, can_access_monitor_folder
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.presentation.path_helpers import (
    enabled_monitor_folder_for_path as _enabled_monitor_folder_for_path,
)
from app.modules.imports.public import (
    execute_import_checkpoint,
    is_supported_import_filename,
    target_directory_from_path as _target_directory_from_path,
)
from app.modules.imports.presentation.mappers import (
    import_task_view as _import_task_view,
    is_inside_path as _is_inside_path,
    monitor_directory_tree_node as _monitor_directory_tree_node,
)
from app.modules.library.public import (
    conversion_output_paths as _conversion_output_paths,
    delete_import_linked_library_scope as _delete_import_linked_library_scope,
    delete_source_paths as _delete_source_paths,
    get_work as _get_work,
    source_delete_path as _source_delete_path,
)
from app.schemas.responses import fail, ok
from app.services.audio_metadata import collect_audio_bundle_files, is_supported_audio_file
from app.services.import_preferences import (
    extension_is_allowed,
    load_import_preferences,
    matches_ignore_patterns,
)

router = APIRouter(tags=["imports-write"])
logger = logging.getLogger(__name__)


def _record_system_event(
    db: Session,
    *,
    level: str = "info",
    source: str,
    action: str,
    message: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_system_event(
        db,
        level=level,
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        message=message,
        metadata=metadata,
        commit=True,
        prune=True,
    )


def _stage_system_event(
    db: Session,
    *,
    level: str = "info",
    source: str,
    action: str,
    message: str,
    actor_type: str = "system",
    actor_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    record_system_event(
        db,
        level=level,
        source=source,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        message=message,
        metadata=metadata,
        commit=False,
        prune=True,
    )

def _visible_import_task_or_none(db: Session, user: User, task_id: str) -> dict[str, Any] | None:
    task = import_http_store.get_import_task(db, task_id)
    if task is None or not can_access_monitor_folder(db, user, task.get("monitorFolderId")):
        return None
    return task


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _auth(db: Session, request: Request, settings: Settings) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _save_system_setting(db: Session, key: str, value: Any) -> None:
    from app.bootstrap.system import upsert_setting

    upsert_setting(db, key, value)


async def _request_json_or_empty(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_upload_name(value: str | None) -> str:
    name = Path(value or "upload").name
    sanitized = re.sub(r"[^A-Za-z0-9._()（）\-\u4e00-\u9fff]+", "_", name).strip("._")
    return sanitized or "upload"


def _audio_bundle_upload_title(file_names: list[str], requested_title: Any = None) -> str:
    explicit = re.sub(r"\s+", " ", str(requested_title or "")).strip()
    if explicit:
        return _safe_upload_name(explicit)
    stems = [Path(_safe_upload_name(name)).stem for name in file_names]
    common = os.path.commonprefix(stems).rstrip(" ._-(（[")
    common = re.sub(r"(?:cd|disc|disk|track|音轨)?\s*\d+\s*$", "", common, flags=re.I).rstrip(" ._-")
    if len(common) >= 2 and not common.isdigit():
        return _safe_upload_name(common)
    first = re.sub(r"^(?:(?:cd|disc|disk)\s*\d+[ ._-]*)?(?:track\s*)?\d+[ ._-]*", "", stems[0], flags=re.I).strip()
    if re.fullmatch(r"(?:序章|前言|尾声|正文|第?\s*\d+\s*[章节集部])", first, re.I):
        first = "未命名有声书"
    return _safe_upload_name(first or "未命名有声书")


def _copy_upload_stream(source: Any, target: Path, max_bytes: int | None = None) -> int:
    copied = 0
    with target.open("xb") as handle:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            copied += len(chunk)
            if max_bytes is not None and copied > max_bytes:
                raise ValueError(f"上传内容超过上限 {max_bytes} bytes")
            handle.write(chunk)
        handle.flush()
        os.fsync(handle.fileno())
    return copied


def _unique_file_in_directory(directory: Path, filename: str) -> Path:
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_upload_name(filename)
    parsed = Path(safe_name)
    stem = parsed.stem or "upload"
    suffix = parsed.suffix
    index = 0
    while True:
        candidate = directory / safe_name if index == 0 else directory / f"{stem}-{index}{suffix}"
        resolved = candidate.resolve()
        if directory != resolved and directory not in resolved.parents:
            raise ValueError("目标路径越界")
        if not resolved.exists():
            return resolved
        index += 1


@router.post("/works/import")
async def import_work(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    form = await request.form()
    files = [value for _key, value in form.multi_items() if hasattr(value, "filename")]
    if not files:
        return fail("请选择要导入的文件", status_code=400)
    upload_file_names = [_safe_upload_name(getattr(upload, "filename", None)) for upload in files]
    unsupported = [
        name
        for name in upload_file_names
        if not is_supported_import_filename(name)
    ]
    if unsupported:
        return fail(
            "当前版本仅支持 EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT、CBZ、ZIP、PDF、M4B、M4A、MP3 格式。",
            status_code=400,
            details={"files": unsupported},
        )
    import_preferences = load_import_preferences(db)
    disabled_extensions = [name for name in upload_file_names if not extension_is_allowed(Path(name), import_preferences)]
    if disabled_extensions:
        return fail("部分文件后缀已在导入偏好中关闭。", status_code=400, details={"files": disabled_extensions})
    try:
        upload_dir = _target_directory_from_path(settings, form.get("targetPath"), "上传")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    ignored_files = [name for name in upload_file_names if matches_ignore_patterns(upload_dir / name, import_preferences.ignore_patterns)]
    if ignored_files:
        return fail("部分文件命中全局导入忽略规则。", status_code=400, details={"files": ignored_files})
    monitor_folder = _enabled_monitor_folder_for_path(db, upload_dir)
    monitor_folder_id = str((monitor_folder or {}).get("id") or "") or None
    if not can_access_monitor_folder(db, user, monitor_folder_id):
        return fail("目标文件夹不存在或无权访问", status_code=404, code="MONITOR_FOLDER_NOT_FOUND")
    auto_import = True
    tasks: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    audio_uploads = [upload for upload in files if is_supported_audio_file(_safe_upload_name(getattr(upload, "filename", None)))]
    explicit_requested_title = re.sub(r"\s+", " ", str(form.get("bookTitle") or "")).strip()[:500] or None
    explicit_requested_author = re.sub(
        r"\s+", " ", str(form.get("bookAuthor") or form.get("author") or "")
    ).strip()[:500] or None
    audio_bundle_dir: Path | None = None
    audio_bundle_staging_dir: Path | None = None
    if len(audio_uploads) > 1:
        bundle_directory_title = _audio_bundle_upload_title(
            [_safe_upload_name(getattr(upload, "filename", None)) for upload in audio_uploads],
            explicit_requested_title,
        )
        audio_bundle_dir = _unique_file_in_directory(upload_dir, f"{bundle_directory_title}-有声书")
        audio_bundle_staging_dir = upload_dir / f".upload-{time_ns()}.part"
        audio_bundle_staging_dir.mkdir(parents=False, exist_ok=False)
    known_audio_sizes = [
        int(size)
        for upload in audio_uploads
        if (size := getattr(upload, "size", None)) is not None
    ]
    if any(size > settings.audiobook_max_file_bytes for size in known_audio_sizes):
        if audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rmdir()
        return fail(f"音频文件超过单文件上限 {settings.audiobook_max_file_bytes} bytes", status_code=400)
    if sum(known_audio_sizes) > settings.audiobook_max_bundle_bytes:
        if audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rmdir()
        return fail(f"有声书文件总量超过上限 {settings.audiobook_max_bundle_bytes} bytes", status_code=400)
    staged_uploads: list[tuple[str, Path, bool, Path]] = []
    finalized_paths: list[Path] = []
    remaining_audio_bytes = settings.audiobook_max_bundle_bytes
    try:
        for upload in files:
            file_name = _safe_upload_name(getattr(upload, "filename", None))
            is_bundle_asset = audio_bundle_dir is not None and is_supported_audio_file(file_name)
            if is_bundle_asset:
                assert audio_bundle_staging_dir is not None
                staged_target = _unique_file_in_directory(audio_bundle_staging_dir, file_name)
                target = audio_bundle_dir / staged_target.name
            else:
                target = _unique_file_in_directory(upload_dir, file_name)
                staged_target = target.with_name(f".{target.name}.{time_ns()}.part")
            is_audio_asset = is_supported_audio_file(file_name)
            max_bytes = min(settings.audiobook_max_file_bytes, remaining_audio_bytes) if is_audio_asset else None
            staged_uploads.append((file_name, target, is_bundle_asset, staged_target))
            copied = _copy_upload_stream(upload.file, staged_target, max_bytes=max_bytes)
            if is_audio_asset:
                remaining_audio_bytes -= copied

        if audio_bundle_dir is not None and audio_bundle_staging_dir is not None:
            audio_bundle_staging_dir.rename(audio_bundle_dir)
            finalized_paths.append(audio_bundle_dir)
        for _file_name, target, is_bundle_asset, staged_target in staged_uploads:
            if is_bundle_asset:
                continue
            staged_target.rename(target)
            finalized_paths.append(target)
    except Exception as exc:
        for _file_name, _target, _is_bundle_asset, staged_target in staged_uploads:
            staged_target.unlink(missing_ok=True)
        if audio_bundle_staging_dir is not None and audio_bundle_staging_dir.exists():
            shutil.rmtree(audio_bundle_staging_dir)
        for path in reversed(finalized_paths):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
        return fail(
            f"保存上传文件失败：{exc}",
            status_code=400 if isinstance(exc, ValueError) else 500,
        )

    saved_uploads: list[tuple[str, Path, bool]] = [
        (file_name, target, is_bundle_asset)
        for file_name, target, is_bundle_asset, _staged_target in staged_uploads
    ]

    queue_items: list[tuple[str, Path, list[tuple[str, Path, bool]]]] = [
        (file_name, target, [(file_name, target, is_bundle_asset)])
        for file_name, target, is_bundle_asset in saved_uploads
        if not is_bundle_asset
    ]
    if audio_bundle_dir is not None:
        queue_items.append((audio_bundle_dir.name, audio_bundle_dir, [item for item in saved_uploads if item[2]]))

    def stage_upload_records() -> None:
        for original_name, source_path, grouped_uploads in queue_items:
            is_audio_queue = all(
                is_supported_audio_file(file_name)
                for file_name, _target, _asset in grouped_uploads
            )
            task, _created = (
                stage_import_task(
                    db,
                    source_path,
                    origin="MANUAL",
                    original_name=original_name,
                    requested_title=explicit_requested_title if is_audio_queue else None,
                    requested_author=explicit_requested_author if is_audio_queue else None,
                    monitor_folder_id=monitor_folder.get("id") if monitor_folder else None,
                    message="有声书分轨已合并，等待后台处理"
                    if len(grouped_uploads) > 1
                    else "已保存到所选目录，等待后台处理",
                )
                if _has_table(db, "ImportTask")
                else ({"id": None, "sourcePath": str(source_path)}, True)
            )
            tasks.append(task)
            for file_name, target, _is_bundle_asset in grouped_uploads:
                _stage_system_event(
                    db,
                    level="info",
                    source="import",
                    actor_type="admin",
                    actor_id=user.id,
                    action="uploaded",
                    target_type="importTask",
                    target_id=task.get("id"),
                    message=f"上传到所选目录：{file_name}",
                    metadata={
                        "file": file_name,
                        "sourcePath": str(target),
                        "bundleSourcePath": str(source_path),
                        "autoImport": True,
                    },
                )
                results.append(
                    {
                        "sourcePath": str(target),
                        "file": file_name,
                        "importTaskId": task.get("id"),
                        "importStatus": "pending",
                        "autoImport": True,
                        "message": "已合并为一个有声书任务"
                        if len(grouped_uploads) > 1
                        else "已加入后台导入队列",
                    }
                )
        _save_system_setting(db, "library.lastUploadTargetPath", str(upload_dir))

    try:
        execute_import_checkpoint(db, stage_upload_records)
    except Exception:
        for path in reversed(finalized_paths):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        logger.exception("failed to persist uploaded import batch")
        return fail("创建导入任务失败", status_code=500)

    task_kind = str(tasks[0].get("taskKind") or "FILE") if len(tasks) == 1 else "MULTI_FILE"
    asset_count = sum(int(task.get("assetCount") or 1) for task in tasks)
    return ok({
        "tasks": tasks,
        "results": results,
        "queued": len(tasks),
        "saved": len(files),
        "imported": 0,
        "autoImport": auto_import,
        "taskKind": task_kind,
        "bundleKey": tasks[0].get("bundleKey") if len(tasks) == 1 else None,
        "assetCount": asset_count,
        "processedAssetCount": sum(int(task.get("processedAssetCount") or 0) for task in tasks),
    })


@router.post("/import-tasks/scan-directory")
async def scan_import_directory(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await _request_json_or_empty(request)
    requested_path = str(payload.get("path") or "").strip()
    node, error, status_code = _monitor_directory_tree_node(settings, requested_path)
    if error or not node:
        return fail(error or "目录不可用", status_code=status_code)
    target_path = Path(str(node["path"])).resolve()
    folder_rows = import_http_store.list_enabled_monitor_folder_rows(db)
    matching_folders = []
    for folder in folder_rows:
        try:
            folder_path = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if _is_inside_path(folder_path, target_path):
            matching_folders.append((folder_path, folder))
    if not matching_folders:
        return fail("所选目录不在已启用的监控文件夹内，请先添加或启用对应监控文件夹", status_code=400)
    _folder_path, folder = max(matching_folders, key=lambda item: len(item[0].parts))
    if not can_access_monitor_folder(db, user, str(folder.get("id"))):
        return fail("目录不可用", status_code=404, code="MONITOR_FOLDER_NOT_FOUND")
    folder_config = monitor_folder_config(folder, preferences=load_import_preferences(db))

    class PersistentQueue:
        def __init__(self) -> None:
            self.queued = 0

        def enqueue(self, path: Path, selected_folder: MonitorFolderConfig) -> None:
            _task, created = enqueue_import_task(
                db,
                path,
                origin="WATCH",
                original_name=path.name,
                monitor_folder_id=selected_folder.id,
                message="从文件管理手动加入导入队列",
                allow_terminal_requeue=path.is_dir(),
            )
            if created:
                self.queued += 1

    queue = PersistentQueue()
    summary = scan_directory_for_imports(
        target_path,
        folder_config,
        queue,
        known_paths=load_known_import_paths(db),
    )
    data = {
        "path": str(target_path),
        "monitorFolderId": folder_config.id,
        "monitorFolderName": folder.get("name"),
        "directoriesScanned": summary.directories_scanned,
        "filesScanned": summary.files_scanned,
        "candidatesFound": summary.candidates_found,
        "queued": queue.queued,
        "skipped": summary.cached_files + summary.ignored_files,
        "errors": summary.errors,
    }
    _record_system_event(
        db,
        level="warning" if summary.errors else "info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="scan.directory.requested",
        target_type="monitorFolder",
        target_id=folder_config.id,
        message=f"从文件管理识别目录：{target_path}",
        metadata=data,
    )
    return ok(data)


@router.delete("/import-tasks")
def clear_import_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    deleted = 0
    if _has_table(db, "ImportTask"):
        context = authorization_context(db, user)
        deleted = import_http_store.clear_terminal_import_tasks(db, context)
    if deleted:
        _record_system_event(db, level="info", source="import", actor_type="admin", actor_id=user.id, action="tasks.cleared", target_type="importTask", message=f"清空已结束导入记录 {deleted} 条", metadata={"deleted": deleted})
    return ok({"deleted": deleted})


@router.delete("/import-tasks/{task_id}")
async def delete_import_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入记录不存在", status_code=404)
    if task.get("status") not in {"COMPLETED", "FAILED"}:
        return fail("导入任务仍在处理中，完成或失败后才能删除记录", status_code=409)

    payload = await _request_json_or_empty(request)
    delete_mode = str(payload.get("deleteMode") or "record").strip().lower()
    delete_library_record = payload.get("deleteLibraryRecord") is True
    if delete_mode not in {"record", "source", "converted"}:
        return fail("删除范围无效", status_code=400)
    work_id = str(task.get("workId") or "").strip()
    work = _get_work(db, work_id) if work_id else None
    if delete_library_record and not work:
        return fail("该导入记录没有可删除的关联书库图书", status_code=400)

    conversion = import_http_store.get_conversion_for_import(db, task_id)
    selected_paths: list[Path] = []
    if delete_mode == "source":
        source_path = _source_delete_path(task.get("sourcePath"), db, settings)
        if not source_path:
            return fail("源文件路径不在允许删除的书库或监控目录中", status_code=400)
        selected_paths = [source_path]
    elif delete_mode == "converted":
        selected_paths = _conversion_output_paths(conversion, settings)
        if not selected_paths:
            return fail("该导入记录没有可删除的转换文件", status_code=400)

    cleanup = _delete_source_paths(selected_paths)
    if cleanup["failedFileDeletes"]:
        return fail("文件删除失败，导入记录已保留，请检查文件权限后重试", status_code=500, details={"failedFileDeletes": cleanup["failedFileDeletes"]})

    library_cleanup = (
        _delete_import_linked_library_scope(db, task, settings)
        if delete_library_record and work
        else {"deleted": False, "deletedWorkRecord": False, "deletedDatabaseRecords": 0, "deletedFiles": 0, "failedFileDeletes": []}
    )

    deleted = import_http_store.delete_import_task_row(db, task_id)
    if deleted:
        _record_system_event(
            db,
            level="warning" if delete_mode != "record" or delete_library_record else "info",
            source="import",
            actor_type="admin",
            actor_id=user.id,
            action="task.deleted",
            target_type="importTask",
            target_id=task_id,
            message=f"删除导入记录{'及关联书库图书' if delete_library_record else ''}：{task.get('originalName') or task.get('sourcePath')}",
            metadata={
                "deleteMode": delete_mode,
                "deleteLibraryRecord": delete_library_record,
                "deletedLibraryRecord": bool(library_cleanup.get("deleted")),
                "deletedWorkRecord": bool(library_cleanup.get("deletedWorkRecord")),
                "deletedLibraryDatabaseRecords": int(library_cleanup.get("deletedDatabaseRecords") or 0),
                "libraryRecordId": work_id or None,
                "deletedFiles": int(cleanup["deletedFiles"]) + int(library_cleanup.get("deletedFiles") or 0),
                "missingFiles": cleanup["missingFiles"],
                "failedFileDeletes": library_cleanup.get("failedFileDeletes") or [],
            },
        )
    return ok({
        "deleted": deleted,
        "id": task_id,
        "deleteMode": delete_mode,
        "deleteLibraryRecord": delete_library_record,
        "deletedLibraryRecord": bool(library_cleanup.get("deleted")),
        "deletedWorkRecord": bool(library_cleanup.get("deletedWorkRecord")),
        "deletedLibraryDatabaseRecords": int(library_cleanup.get("deletedDatabaseRecords") or 0),
        "libraryRecordId": work_id or None,
        "deletedFiles": int(cleanup["deletedFiles"]) + int(library_cleanup.get("deletedFiles") or 0),
        "missingFiles": cleanup["missingFiles"],
        "failedFileDeletes": library_cleanup.get("failedFileDeletes") or [],
    })


@router.post("/import-tasks/rescan")
def rescan_import_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    requested_at = _now().isoformat()
    context = authorization_context(db, user)
    requested_value = (
        requested_at
        if context.is_admin
        else _json_text(
            {
                "requestedAt": requested_at,
                "monitorFolderIds": list(context.monitor_folder_ids),
            }
        )
    )
    if not context.is_admin and not context.monitor_folder_ids:
        return fail("没有可重新识别的授权文件夹", status_code=403, code="NO_IMPORT_SCOPE")
    if _has_table(db, "SystemSetting"):
        import_http_store.request_monitor_rescan(db, requested_value)
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="rescan.requested",
        target_type="monitorFolder",
        message="请求重新识别监控文件夹",
        metadata={
            "requestedAt": requested_at,
            "monitorFolderIds": None if context.is_admin else list(context.monitor_folder_ids),
        },
    )
    return ok(
        {
            "requestedAt": requested_at,
            "monitorFolderIds": None if context.is_admin else list(context.monitor_folder_ids),
        }
    )


@router.post("/import-tasks/{task_id}/retry")
def retry_import_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入任务不存在", status_code=404)
    if task.get("status") != "FAILED":
        return fail("只有失败的任务可以重试", status_code=400)
    if not bool(task.get("retryable")):
        return fail("该错误无法通过自动重试解决，原文件已保留", status_code=400)
    source_path = Path(str(task.get("sourcePath") or ""))
    try:
        source_available = source_path.is_file() or (source_path.is_dir() and bool(collect_audio_bundle_files(source_path)))
    except ValueError:
        source_available = False
    if not source_available:
        return fail("原文件不存在，无法重试", status_code=400)
    updated_at = _now()
    task = import_http_store.reset_import_task_for_retry(
        db,
        task_id,
        updated_at=updated_at,
    )
    if _has_table(db, "ImportAsset"):
        import_http_store.reset_import_assets_for_retry(db, task_id, updated_at=_now())
    conversion = import_http_store.reset_conversion_for_retry(
        db,
        task_id,
        updated_at=updated_at,
    )
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="retry",
        target_type="importTask",
        target_id=task_id,
        message=f"重新排队导入任务：{task.get('originalName') or task.get('sourcePath')}",
        metadata={"errorCode": conversion.get("errorCode") if conversion else None},
    )
    return ok({"task": _import_task_view(db, task or {}, log_limit=100)})
