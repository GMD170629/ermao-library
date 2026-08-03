"""Imports write HTTP surface: upload, scan, delete, retry, rescan."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Never

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    cancel_import_scan_job as cancel_import_scan_job_command,
)
from app.bootstrap.imports import (
    enqueue_import_task,
    execute_recoverable_import_deletion,
    import_http_store,
    save_uploaded_files,
    schedule_import_scan_job,
)
from app.bootstrap.imports import (
    get_import_scan_job as get_import_scan_job_query,
)
from app.bootstrap.imports import (
    list_import_scan_jobs as list_import_scan_jobs_query,
)
from app.bootstrap.system import (
    active_health_run_id,
    create_queue_operation,
    queue_runtime_view,
    record_system_event,
    upsert_setting,
)
from app.contracts.http_errors import ErrorResponses
from app.core.authorization import authorization_context, can_access_monitor_folder
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.application.work_queue_dto import ImportScanJobDTO
from app.modules.imports.presentation.mappers import (
    import_task_view as _import_task_view,
)
from app.modules.imports.presentation.mappers import (
    is_inside_path as _is_inside_path,
)
from app.modules.imports.presentation.mappers import (
    monitor_directory_tree_node as _monitor_directory_tree_node,
)
from app.modules.imports.presentation.path_helpers import (
    enabled_monitor_folder_for_path as _enabled_monitor_folder_for_path,
)
from app.modules.imports.presentation.schemas import (
    DeletedImportTasksResponse,
    ImportBadRequestError,
    ImportConflictError,
    ImportDeletionFailureDetails,
    ImportDeletionResponse,
    ImportDirectoryScanResponse,
    ImportErrorBody,
    ImportFileListDetails,
    ImportForbiddenError,
    ImportInternalError,
    ImportNotFoundError,
    ImportQueueClearPayload,
    ImportQueueClearResponse,
    ImportScanJobResponse,
    ImportScanJobsResponse,
    ImportTaskResponse,
    ImportUploadResponse,
    RescanImportTasksResponse,
)
from app.modules.imports.presentation.schemas import (
    ImportScanJob as ImportScanJobContract,
)
from app.modules.imports.public import (
    ImportFileQuarantineError,
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadPublicationError,
    UploadSource,
    execute_import_checkpoint,
    is_supported_import_filename,
    safe_upload_filename,
)
from app.modules.imports.public import (
    target_directory_from_path as _target_directory_from_path,
)
from app.modules.library.public import (
    collect_import_linked_library_scope_paths as _collect_import_linked_library_scope_paths,
)
from app.modules.library.public import (
    conversion_output_paths as _conversion_output_paths,
)
from app.modules.library.public import (
    delete_import_linked_library_scope as _delete_import_linked_library_scope,
)
from app.modules.library.public import (
    get_work as _get_work,
)
from app.modules.library.public import (
    source_delete_path as _source_delete_path,
)
from app.schemas.responses import ok
from app.services.audio_metadata import (
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import (
    extension_is_allowed,
    load_import_preferences,
    matches_ignore_patterns,
)

router = APIRouter(tags=["imports-write"], route_class=TypedContractRoute)
logger = logging.getLogger(__name__)


def _raise_import_error(
    message: str,
    status_code: int = 400,
    details: ImportFileListDetails | ImportDeletionFailureDetails | None = None,
    *,
    code: str | None = None,
) -> Never:
    body = ImportErrorBody(message=message, code=code, details=details)
    if status_code == 403:
        raise ImportForbiddenError(body)
    if status_code == 404:
        raise ImportNotFoundError(body)
    if status_code == 409:
        raise ImportConflictError(body)
    if status_code == 500:
        raise ImportInternalError(body)
    raise ImportBadRequestError(body)


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
    )


def _visible_import_task_or_none(
    db: Session, user: User, task_id: str
) -> dict[str, Any] | None:
    task = import_http_store.get_import_task(db, task_id)
    if task is None or not can_access_monitor_folder(
        db, user, task.get("monitorFolderId")
    ):
        return None
    return task


def _scan_job_contract(job: ImportScanJobDTO) -> ImportScanJobContract:
    return ImportScanJobContract.model_validate(job, from_attributes=True)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _now() -> datetime:
    return datetime.now(UTC)


def _save_system_setting(db: Session, key: str, value: Any) -> None:

    upsert_setting(db, key, value)


async def _request_json_or_empty(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


@router.post("/works/import")
async def import_work(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportUploadResponse,
    ErrorResponses(ImportBadRequestError, ImportNotFoundError, ImportInternalError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    form = await request.form()
    files = [
        value for _key, value in form.multi_items() if isinstance(value, UploadFile)
    ]
    if not files:
        _raise_import_error("请选择要导入的文件", status_code=400)
    upload_file_names = [
        safe_upload_filename(upload.filename or "upload") for upload in files
    ]
    unsupported = [
        name for name in upload_file_names if not is_supported_import_filename(name)
    ]
    if unsupported:
        _raise_import_error(
            "当前版本不支持以下文件后缀。",
            status_code=400,
            details=ImportFileListDetails(files=unsupported),
        )
    import_preferences = load_import_preferences(db)
    disabled_extensions = [
        name
        for name in upload_file_names
        if not extension_is_allowed(Path(name), import_preferences)
    ]
    if disabled_extensions:
        _raise_import_error(
            "部分文件后缀已在导入偏好中关闭。",
            status_code=400,
            details=ImportFileListDetails(files=disabled_extensions),
        )
    try:
        upload_dir = _target_directory_from_path(form.get("targetPath"), "上传")
    except ValueError as exc:
        _raise_import_error(str(exc), status_code=400)
    ignored_files = [
        name
        for name in upload_file_names
        if matches_ignore_patterns(
            upload_dir / name, import_preferences.ignore_patterns
        )
    ]
    if ignored_files:
        _raise_import_error(
            "部分文件命中全局导入忽略规则。",
            status_code=400,
            details=ImportFileListDetails(files=ignored_files),
        )
    monitor_folder = _enabled_monitor_folder_for_path(db, upload_dir)
    if monitor_folder is None:
        _raise_import_error(
            "上传目录必须位于已启用的监控文件夹中",
            status_code=400,
            code="UPLOAD_TARGET_NOT_MONITORED",
        )
    monitor_folder_id = str((monitor_folder or {}).get("id") or "") or None
    if not can_access_monitor_folder(db, user, monitor_folder_id):
        _raise_import_error(
            "目标文件夹不存在或无权访问",
            status_code=404,
            code="MONITOR_FOLDER_NOT_FOUND",
        )
    sources = tuple(
        UploadSource(
            filename=file_name,
            stream=upload.file,
            is_audio=is_supported_audio_file(file_name),
            max_bytes=(
                settings.audiobook_max_file_bytes
                if is_supported_audio_file(file_name)
                else None
            ),
        )
        for upload, file_name in zip(files, upload_file_names, strict=True)
    )
    execute_import_checkpoint(
        db,
        lambda: _save_system_setting(
            db, "library.lastUploadTargetPath", str(upload_dir)
        ),
    )
    try:
        saved_uploads = save_uploaded_files(
            SaveUploadedFilesCommand(
                target_directory=upload_dir,
                sources=sources,
                audio_bundle_max_bytes=settings.audiobook_max_bundle_bytes,
            )
        )
    except UploadFileTooLargeError:
        _raise_import_error("上传文件超过允许的大小", status_code=400)
    except UploadPublicationError:
        logger.exception(
            "upload.files_save_failed",
            extra={"actor_id": user.id, "target_directory": str(upload_dir)},
        )
        _raise_import_error("保存上传文件失败", status_code=500)

    auto_import = monitor_folder is not None
    monitoring_status = "WATCHING" if auto_import else "NOT_MONITORED"
    logger.info(
        "upload.files_saved",
        extra={
            "actor_id": user.id,
            "target_directory": str(upload_dir),
            "file_count": len(saved_uploads),
            "monitoring_status": monitoring_status,
        },
    )
    return ImportUploadResponse(
        data={
            "results": [
                {
                    "sourcePath": str(saved.path),
                    "file": saved.filename,
                    "sizeBytes": saved.size_bytes,
                    "monitoringStatus": monitoring_status,
                }
                for saved in saved_uploads
            ],
            "saved": len(saved_uploads),
            "autoImport": auto_import,
        }
    )


@router.post("/import-tasks/scan-directory", status_code=202)
async def scan_import_directory(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportDirectoryScanResponse,
    ErrorResponses(ImportBadRequestError, ImportForbiddenError, ImportNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await _request_json_or_empty(request)
    requested_path = str(payload.get("path") or "").strip()
    node, error, status_code = _monitor_directory_tree_node(requested_path)
    if error or not node:
        _raise_import_error(error or "目录不可用", status_code=status_code)
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
        _raise_import_error(
            "所选目录不在已启用的监控文件夹内，请先添加或启用对应监控文件夹",
            status_code=400,
        )
    _folder_path, folder = max(matching_folders, key=lambda item: len(item[0].parts))
    if not can_access_monitor_folder(db, user, str(folder.get("id"))):
        _raise_import_error(
            "目录不可用", status_code=404, code="MONITOR_FOLDER_NOT_FOUND"
        )
    job, created = schedule_import_scan_job(
        db,
        monitor_folder_id=str(folder["id"]),
        actor_user_id=user.id,
        root_path=target_path,
        trigger="MANUAL_DIRECTORY",
    )
    _record_system_event(
        db,
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="scan.directory.requested",
        target_type="monitorFolder",
        target_id=str(folder["id"]),
        message=f"从文件管理识别目录：{target_path}",
        metadata={"scanJobId": job.id, "created": created, "path": str(target_path)},
    )
    return ImportDirectoryScanResponse(
        data={"job": _scan_job_contract(job), "created": created}
    )


@router.delete("/import-tasks")
def clear_import_tasks(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedImportTasksResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    deleted = 0
    if _has_table(db, "ImportTask"):
        context = authorization_context(db, user)
        deleted = import_http_store.clear_terminal_import_tasks(db, context)
    if deleted:
        _record_system_event(
            db,
            level="info",
            source="import",
            actor_type="admin",
            actor_id=user.id,
            action="tasks.cleared",
            target_type="importTask",
            message=f"清空已结束导入记录 {deleted} 条",
            metadata={"deleted": deleted},
        )
    return ok({"deleted": deleted})


@router.post("/import-tasks/clear", status_code=202)
def request_clear_import_queue(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportQueueClearResponse,
    ErrorResponses(ImportConflictError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if active_health_run_id(db):
        _raise_import_error(
            "健康检查运行期间不能清理导入队列",
            status_code=409,
            code="HEALTH_RUN_ACTIVE",
        )
    runtime = queue_runtime_view(db, "import")
    if runtime is None or runtime.get("stale") or runtime.get("status") != "running":
        _raise_import_error(
            "导入工作进程当前不可用",
            status_code=409,
            code="IMPORT_QUEUE_OFFLINE",
        )
    operation, created = create_queue_operation(db, user.id, action="clear")
    if operation.get("action") != "clear":
        _raise_import_error(
            "导入队列正在执行其他控制操作",
            status_code=409,
            code="QUEUE_OPERATION_CONFLICT",
        )
    return ImportQueueClearResponse(
        data=ImportQueueClearPayload.model_validate(
            {"operation": operation, "created": created}
        )
    )


@router.delete("/import-tasks/{task_id}")
async def delete_import_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportDeletionResponse,
    ErrorResponses(
        ImportBadRequestError,
        ImportNotFoundError,
        ImportConflictError,
        ImportInternalError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        _raise_import_error("导入记录不存在", status_code=404)
    if task.get("status") not in {"COMPLETED", "FAILED"}:
        _raise_import_error(
            "导入任务仍在处理中，完成或失败后才能删除记录", status_code=409
        )

    payload = await _request_json_or_empty(request)
    delete_mode = str(payload.get("deleteMode") or "record").strip().lower()
    delete_library_record = payload.get("deleteLibraryRecord") is True
    if delete_mode not in {"record", "source", "converted"}:
        _raise_import_error("删除范围无效", status_code=400)
    work_id = str(task.get("workId") or "").strip()
    work = _get_work(db, work_id) if work_id else None
    if delete_library_record and not work:
        _raise_import_error("该导入记录没有可删除的关联书库图书", status_code=400)

    conversion = import_http_store.get_conversion_for_import(db, task_id)
    selected_paths: list[Path] = []
    if delete_mode == "source":
        source_path = _source_delete_path(task.get("sourcePath"), db, settings)
        if not source_path:
            _raise_import_error(
                "源文件路径不在允许删除的书库或监控目录中", status_code=400
            )
        selected_paths = [source_path]
    elif delete_mode == "converted":
        selected_paths = _conversion_output_paths(conversion, settings)
        if not selected_paths:
            _raise_import_error("该导入记录没有可删除的转换文件", status_code=400)

    library_paths = (
        _collect_import_linked_library_scope_paths(db, task, settings)
        if delete_library_record and work
        else []
    )
    deletion_paths = [*selected_paths, *library_paths]
    monitor_roots = [
        Path(root).expanduser()
        for root in import_http_store.list_monitor_root_paths(db)
        if root.strip()
    ]
    source_path_value = str(task.get("sourcePath") or "").strip()
    if source_path_value:
        try:
            source_parent = Path(source_path_value).expanduser().resolve().parent
            monitor_roots.append(source_parent)
        except (OSError, RuntimeError):
            pass
    def delete_database_records() -> tuple[bool, dict[str, Any]]:
        library_cleanup = (
            _delete_import_linked_library_scope(db, task, settings)
            if delete_library_record and work
            else {
                "deleted": False,
                "deletedWorkRecord": False,
                "deletedDatabaseRecords": 0,
                "deletedFiles": 0,
                "failedFileDeletes": [],
            }
        )
        deleted = import_http_store.delete_import_task_row(db, task_id)
        if deleted:
            _stage_system_event(
                db,
                level="warning"
                if delete_mode != "record" or delete_library_record
                else "info",
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
                    "deletedLibraryDatabaseRecords": int(
                        library_cleanup.get("deletedDatabaseRecords") or 0
                    ),
                    "libraryRecordId": work_id or None,
                    "plannedFileDeletes": len(deletion_paths),
                },
            )
        return deleted, library_cleanup

    try:
        deletion_result, file_cleanup = execute_recoverable_import_deletion(
            db,
            settings,
            owner_id=task_id,
            paths=[str(path) for path in deletion_paths],
            monitor_roots=monitor_roots,
            database_operation=delete_database_records,
        )
        deleted, library_cleanup = deletion_result
    except ImportFileQuarantineError as exc:
        _raise_import_error(
            "文件删除失败，导入记录已保留，请检查文件权限后重试",
            status_code=500,
            details=ImportDeletionFailureDetails(
                failedFileDeletes=[
                    {"path": item.path, "message": item.message}
                    for item in exc.failures
                ],
            ),
        )
    failed_file_deletes = [
        {"path": item.path, "message": item.message} for item in file_cleanup.failures
    ]
    return ImportDeletionResponse(
        data={
            "deleted": deleted,
            "id": task_id,
            "deleteMode": delete_mode,
            "deleteLibraryRecord": delete_library_record,
            "deletedLibraryRecord": bool(library_cleanup.get("deleted")),
            "deletedWorkRecord": bool(library_cleanup.get("deletedWorkRecord")),
            "deletedLibraryDatabaseRecords": int(
                library_cleanup.get("deletedDatabaseRecords") or 0
            ),
            "libraryRecordId": work_id or None,
            "deletedFiles": file_cleanup.deleted_files,
            "missingFiles": list(file_cleanup.missing_paths),
            "failedFileDeletes": failed_file_deletes,
        }
    )


@router.post("/import-tasks/rescan", status_code=202)
def rescan_import_tasks(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[RescanImportTasksResponse, ErrorResponses(ImportForbiddenError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    requested_at = _now()
    context = authorization_context(db, user)
    if not context.is_admin and not context.monitor_folder_ids:
        _raise_import_error(
            "没有可重新识别的授权文件夹", status_code=403, code="NO_IMPORT_SCOPE"
        )
    allowed_ids = None if context.is_admin else set(context.monitor_folder_ids)
    jobs: list[ImportScanJobDTO] = []
    created_count = 0
    for folder in import_http_store.list_enabled_monitor_folder_rows(db):
        folder_id = str(folder.get("id") or "")
        if not folder_id or (allowed_ids is not None and folder_id not in allowed_ids):
            continue
        root_path = str(folder.get("rootPath") or "").strip()
        if not root_path:
            continue
        job, created = schedule_import_scan_job(
            db,
            monitor_folder_id=folder_id,
            actor_user_id=user.id,
            root_path=Path(root_path),
            trigger="RESCAN",
        )
        jobs.append(job)
        created_count += int(created)
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
            "requestedAt": requested_at.isoformat(),
            "scanJobIds": [job.id for job in jobs],
            "createdCount": created_count,
        },
    )
    return RescanImportTasksResponse(
        data={
            "requestedAt": requested_at,
            "jobs": [_scan_job_contract(job) for job in jobs],
        }
    )


def _visible_scan_job_or_none(
    db: Session, user: User, job_id: str
) -> ImportScanJobDTO | None:
    job = get_import_scan_job_query(db, job_id)
    if job is None or not can_access_monitor_folder(db, user, job.monitor_folder_id):
        return None
    return job


@router.get("/import-scan-jobs")
def list_import_scan_jobs(
    request: Request,
    status: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportScanJobsResponse,
    ErrorResponses(ImportBadRequestError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if status is not None and status not in {
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
    }:
        _raise_import_error(
            "扫描任务状态无效", status_code=400, code="INVALID_SCAN_JOB_STATUS"
        )
    context = authorization_context(db, user)
    jobs = list_import_scan_jobs_query(
        db,
        monitor_folder_ids=None
        if context.is_admin
        else tuple(context.monitor_folder_ids),
        status=status,
    )
    return ImportScanJobsResponse(
        data={"jobs": [_scan_job_contract(job) for job in jobs]}
    )


@router.get("/import-scan-jobs/{job_id}")
def get_import_scan_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[ImportScanJobResponse, ErrorResponses(ImportNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    job = _visible_scan_job_or_none(db, user, job_id)
    if job is None:
        _raise_import_error(
            "扫描任务不存在", status_code=404, code="IMPORT_SCAN_JOB_NOT_FOUND"
        )
    return ImportScanJobResponse(data={"job": _scan_job_contract(job)})


@router.post("/import-scan-jobs/{job_id}/cancel")
def cancel_import_scan_job(
    job_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[ImportScanJobResponse, ErrorResponses(ImportNotFoundError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    job = _visible_scan_job_or_none(db, user, job_id)
    if job is None:
        _raise_import_error(
            "扫描任务不存在", status_code=404, code="IMPORT_SCAN_JOB_NOT_FOUND"
        )
    cancel_import_scan_job_command(db, job_id)
    updated = get_import_scan_job_query(db, job_id)
    if updated is None:
        _raise_import_error(
            "扫描任务不存在", status_code=404, code="IMPORT_SCAN_JOB_NOT_FOUND"
        )
    return ImportScanJobResponse(data={"job": _scan_job_contract(updated)})


@router.post("/import-tasks/{task_id}/retry")
def retry_import_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportTaskResponse, ErrorResponses(ImportBadRequestError, ImportNotFoundError)
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        _raise_import_error("导入任务不存在", status_code=404)
    if task.get("status") != "FAILED":
        _raise_import_error("只有失败的任务可以重试", status_code=400)
    if not bool(task.get("retryable")):
        _raise_import_error("该错误无法通过自动重试解决，原文件已保留", status_code=400)
    source_path = Path(str(task.get("sourcePath") or ""))
    try:
        source_available = source_path.is_file() or (
            source_path.is_dir() and bool(collect_audio_bundle_files(source_path))
        )
    except (AudioTrackLimitExceededError, ValueError):
        source_available = False
    if not source_available:
        _raise_import_error("原文件不存在，无法重试", status_code=400)
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
    if task is not None:
        enqueue_import_task(
            db,
            source_path,
            origin=str(task.get("origin") or "MANUAL"),
            original_name=str(task.get("originalName") or source_path.name),
            requested_title=task.get("requestedTitle"),
            requested_author=task.get("requestedAuthor"),
            work_id=task.get("workId"),
            monitor_folder_id=task.get("monitorFolderId"),
            message="等待后台重试",
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
