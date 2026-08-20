"""Imports write HTTP surface: upload, scan, delete, retry, rescan."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Never
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    cancel_import_scan_job as cancel_import_scan_job_command,
)
from app.bootstrap.imports import (
    get_import_scan_job as get_import_scan_job_query,
)
from app.bootstrap.imports import (
    import_http_store,
    load_persisted_scan_requests,
    persist_import_scan_requests,
    persist_import_task_retry,
    persist_terminal_import_tasks_clear,
    save_uploaded_files,
)
from app.bootstrap.imports import (
    list_import_scan_jobs as list_import_scan_jobs_query,
)
from app.bootstrap.system import (
    active_health_run_id,
    create_queue_operation,
    persist_system_setting_values,
    prepare_system_setting_values,
    queue_runtime_view,
)
from app.contracts.http_errors import ErrorResponses
from app.core.authorization import authorization_context, can_access_library
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.application.errors import AudioTrackLimitExceededError
from app.modules.imports.application.maintenance_commands import (
    PreparedTerminalImportClear,
    prepare_import_retry,
)
from app.modules.imports.application.scan_jobs import prepare_import_scan_job
from app.modules.imports.application.work_queue_dto import ImportScanJobDTO
from app.modules.imports.presentation.mappers import (
    import_task_view as _import_task_view,
)
from app.modules.imports.presentation.mappers import (
    is_inside_path as _is_inside_path,
)
from app.modules.imports.presentation.mappers import (
    library_directory_tree_node as _library_directory_tree_node,
)
from app.modules.imports.presentation.path_helpers import (
    enabled_library_for_path as _enabled_library_for_path,
)
from app.modules.imports.presentation.schemas import (
    DeletedImportTasksResponse,
    ImportBadRequestError,
    ImportConflictError,
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
    ScanImportDirectoryRequest,
)
from app.modules.imports.presentation.schemas import (
    ImportScanJob as ImportScanJobContract,
)
from app.modules.imports.public import (
    SaveUploadedFilesCommand,
    UploadFileTooLargeError,
    UploadPublicationError,
    UploadSource,
    is_supported_import_filename,
    safe_upload_filename,
)
from app.modules.imports.public import (
    target_directory_from_path as _target_directory_from_path,
)
from app.schemas.responses import ok
from app.services.audio_metadata import (
    collect_audio_bundle_files,
    is_supported_audio_file,
)
from app.services.import_preferences import (
    extension_is_allowed,
    load_raw_import_preferences_projection,
    matches_ignore_patterns,
    prepare_import_preferences,
)
from app.services.system_events import (
    prepare_system_event,
)

router = APIRouter(tags=["imports-write"], route_class=TypedContractRoute)
logger = logging.getLogger(__name__)


def _raise_import_error(
    message: str,
    status_code: int = 400,
    details: ImportFileListDetails | None = None,
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


def _visible_import_task_or_none(
    db: Session, user: User, task_id: str
) -> dict[str, Any] | None:
    task = import_http_store.get_import_task(db, task_id)
    if task is None or not can_access_library(db, user, task.get("libraryId")):
        return None
    return task


def _scan_job_contract(job: ImportScanJobDTO) -> ImportScanJobContract:
    return ImportScanJobContract.model_validate(job, from_attributes=True)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except SQLAlchemyError:
        return False


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("/works/import")
def import_work(
    request: Request,
    file: Annotated[list[UploadFile] | None, File()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    target_path: Annotated[str | None, Form(alias="targetPath")] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportUploadResponse,
    ErrorResponses(ImportBadRequestError, ImportNotFoundError, ImportInternalError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    uploads = [*(file or []), *(files or [])]
    if not uploads:
        _raise_import_error("请选择要导入的文件", status_code=400)
    upload_file_names = [
        safe_upload_filename(upload.filename or "upload") for upload in uploads
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
    preference_projection = load_raw_import_preferences_projection(db)
    db.close()
    import_preferences = prepare_import_preferences(preference_projection)
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
        upload_dir = _target_directory_from_path(target_path, "上传")
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
    library = _enabled_library_for_path(db, upload_dir)
    if library is None:
        _raise_import_error(
            "上传目录必须位于已启用的书库中",
            status_code=400,
            code="UPLOAD_TARGET_OUTSIDE_LIBRARY",
        )
    library_id = str((library or {}).get("id") or "") or None
    if not can_access_library(db, user, library_id):
        _raise_import_error(
            "目标文件夹不存在或无权访问",
            status_code=404,
            code="LIBRARY_NOT_FOUND",
        )
    db.close()
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
        for upload, file_name in zip(uploads, upload_file_names, strict=True)
    )
    prepared_upload_target = prepare_system_setting_values(
        {"library.lastUploadTargetPath": str(upload_dir)}
    )
    persist_system_setting_values(db, prepared_upload_target)
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

    logger.info(
        "upload.files_saved",
        extra={
            "actor_id": user.id,
            "target_directory": str(upload_dir),
            "file_count": len(saved_uploads),
            "library_id": library_id,
        },
    )
    return ImportUploadResponse(
        data={
            "results": [
                {
                    "sourcePath": str(saved.path),
                    "file": saved.filename,
                    "sizeBytes": saved.size_bytes,
                }
                for saved in saved_uploads
            ],
            "saved": len(saved_uploads),
        }
    )


@router.post("/import-tasks/scan-directory", status_code=202)
def scan_import_directory(
    request: Request,
    payload: Annotated[ScanImportDirectoryRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportDirectoryScanResponse,
    ErrorResponses(ImportBadRequestError, ImportForbiddenError, ImportNotFoundError),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    requested_path = str(payload.path if payload is not None else "").strip()
    node, error, status_code = _library_directory_tree_node(requested_path)
    if error or not node:
        _raise_import_error(error or "目录不可用", status_code=status_code)
    target_path = Path(str(node["path"])).resolve()
    folder_rows = import_http_store.list_enabled_library_rows(db)
    db.close()
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
            "所选目录不在已启用的书库内，请先添加或启用对应书库",
            status_code=400,
        )
    folder_path, folder = max(matching_folders, key=lambda item: len(item[0].parts))
    if not can_access_library(db, user, str(folder.get("id"))):
        _raise_import_error("目录不可用", status_code=404, code="LIBRARY_NOT_FOUND")
    db.close()
    checkpoint_at = _now()
    prepared_job = prepare_import_scan_job(
        job_id=f"scan_{uuid4().hex}",
        work_item_id=f"work_{uuid4().hex}",
        library_id=str(folder["id"]),
        actor_user_id=user.id,
        canonical_root_path=str(folder_path),
        trigger="MANUAL_ROOT_SCAN",
        available_at=None,
        created_at=checkpoint_at,
    )
    prepared_event = prepare_system_event(
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="scan.directory.requested",
        target_type="library",
        target_id=str(folder["id"]),
        message=f"请求扫描书库根目录：{folder_path}",
        metadata={
            "scanJobId": prepared_job.job_id,
            "rootPath": str(folder_path),
            "requestedPath": str(target_path),
        },
    )
    created_count = persist_import_scan_requests(
        db,
        (prepared_job,),
        (prepared_event,),
    )
    jobs = load_persisted_scan_requests(db, (prepared_job,))
    db.close()
    if not jobs:
        raise RuntimeError("persisted scan request could not be resolved")
    job = jobs[0]
    created = created_count == 1
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
        task_ids = import_http_store.list_terminal_import_task_ids(db, context)
        db.close()
        if task_ids:
            prepared_event = prepare_system_event(
                level="info",
                source="import",
                actor_type="admin",
                actor_id=user.id,
                action="tasks.cleared",
                target_type="importTask",
                message=f"清空已结束导入记录 {len(task_ids)} 条",
                metadata={"deleted": len(task_ids)},
            )
            deleted = persist_terminal_import_tasks_clear(
                db,
                PreparedTerminalImportClear(task_ids, (prepared_event,)),
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
def delete_import_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    ImportDeletionResponse,
    ErrorResponses(
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

    prepared_deletion_event = prepare_system_event(
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="task.deleted",
        target_type="importTask",
        target_id=task_id,
        message=f"删除导入记录：{task.get('originalName') or task.get('sourcePath')}",
        metadata={},
    )
    deleted = persist_terminal_import_tasks_clear(
        db,
        PreparedTerminalImportClear(
            task_ids=(task_id,),
            events=(prepared_deletion_event,),
        ),
    )
    if deleted != 1:
        _raise_import_error("导入记录不存在", status_code=404)
    return ImportDeletionResponse(data={"deleted": True, "id": task_id})


@router.post("/import-tasks/rescan", status_code=202)
def rescan_import_tasks(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[RescanImportTasksResponse, ErrorResponses(ImportForbiddenError)]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    context = authorization_context(db, user)
    if not context.is_admin and not context.library_ids:
        _raise_import_error(
            "没有可重新识别的授权文件夹", status_code=403, code="NO_IMPORT_SCOPE"
        )
    allowed_ids = None if context.is_admin else set(context.library_ids)
    folder_rows = tuple(import_http_store.list_enabled_library_rows(db))
    db.close()
    requested_at = _now()
    prepared_jobs = []
    for folder in folder_rows:
        folder_id = str(folder.get("id") or "")
        if not folder_id or (allowed_ids is not None and folder_id not in allowed_ids):
            continue
        root_path = str(folder.get("rootPath") or "").strip()
        if not root_path:
            continue
        canonical_root = Path(root_path).expanduser().resolve()
        prepared_jobs.append(
            prepare_import_scan_job(
                job_id=f"scan_{uuid4().hex}",
                work_item_id=f"work_{uuid4().hex}",
                library_id=folder_id,
                actor_user_id=user.id,
                canonical_root_path=str(canonical_root),
                trigger="RESCAN",
                available_at=None,
                created_at=requested_at,
            )
        )
    prepared_jobs_tuple = tuple(prepared_jobs)
    prepared_event = prepare_system_event(
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="rescan.requested",
        target_type="library",
        message="请求重新识别书库",
        metadata={
            "requestedAt": requested_at.isoformat(),
            "scanJobIds": [job.job_id for job in prepared_jobs_tuple],
        },
    )
    persist_import_scan_requests(db, prepared_jobs_tuple, (prepared_event,))
    jobs = load_persisted_scan_requests(db, prepared_jobs_tuple)
    db.close()
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
    if job is None or not can_access_library(db, user, job.library_id):
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
        library_ids=None if context.is_admin else tuple(context.library_ids),
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
    db.close()
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
    prepared_event = prepare_system_event(
        level="info",
        source="import",
        actor_type="admin",
        actor_id=user.id,
        action="retry",
        target_type="importTask",
        target_id=task_id,
        message=f"重新排队导入任务：{task.get('originalName') or task.get('sourcePath')}",
        metadata={"errorCode": task.get("errorCode")},
    )
    prepared_retry = prepare_import_retry(
        task_id=task_id,
        source_path=source_path.expanduser().resolve(),
        updated_at=updated_at,
        event=prepared_event,
    )
    persist_import_task_retry(db, prepared_retry)
    refreshed_task = import_http_store.get_import_task(db, task_id)
    hydrated_task = import_http_store.hydrate_import_task_page(
        db,
        [refreshed_task or {}],
        log_limit=100,
    )[0]
    db.close()
    return ok({"task": _import_task_view(db, hydrated_task, log_limit=100)})
