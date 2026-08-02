"""Download-task HTTP surface."""

from __future__ import annotations

import json
from pathlib import Path
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.download import (
    create_download_task as create_download_task_command,
    delete_download_task as delete_download_task_command,
    get_download_task as get_download_task_query,
    list_download_tasks as list_download_tasks_query,
    update_download_task as update_download_task_command,
)
from app.bootstrap.system import record_system_event, upsert_setting
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.download.presentation.sources import router as sources_router
from app.modules.download.presentation.schemas import (
    DeletedDownloadTaskResponse,
    DownloadTaskResponse,
    DownloadTasksResponse,
)
from app.modules.download.public import CreateDownloadTask, UpdateDownloadTask
from app.modules.imports.public import target_directory_from_path as _target_directory_from_path
from app.bootstrap.imports import import_http_store
from app.schemas.responses import fail, ok
from app.services.download_executor import execute_download_task

router = APIRouter(tags=["download"], route_class=TypedContractRoute)
router.include_router(sources_router)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _save_system_setting(db: Session, key: str, value: Any) -> None:
    upsert_setting(db, key, value)


def _has_table(db: Session, table: str) -> bool:
    from sqlalchemy import inspect

    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


def _enabled_monitor_folder_for_path(db: Session, target: Path) -> dict[str, Any] | None:
    from app.modules.imports.public import is_inside_path

    if not _has_table(db, "MonitorFolder"):
        return None
    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in import_http_store.list_enabled_monitor_folder_rows(db):
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or is_inside_path(root, real_target):
            return folder
    return None


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except Exception:
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


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


@router.get("/download-tasks")
def list_download_tasks(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadTasksResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    tasks = [task.to_legacy_dict() for task in list_download_tasks_query(db, limit=1000)]
    return ok({
        "tasks": [
            {
                **task,
                "remoteRef": _parse_json(task.get("remoteRef"), task.get("remoteRef")),
                "sourceName": None,
                "autoImport": _enabled_monitor_folder_for_path(db, Path(str(task.get("savePath") or ""))) is not None,
            }
            for task in tasks
        ]
    })


@router.post("/download-tasks")
async def create_download_task(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    try:
        target_dir = _target_directory_from_path(payload.get("targetPath"), "下载")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    save_path = str(target_dir)
    task = create_download_task_command(
        db,
        CreateDownloadTask(
            id=f"py_{time_ns()}",
            source_id=str(payload["sourceId"]) if payload.get("sourceId") is not None else None,
            search_record_id=str(payload["searchRecordId"]) if payload.get("searchRecordId") is not None else None,
            book_id=str(payload["bookId"]) if payload.get("bookId") is not None else None,
            task_type=str(payload.get("type") or "manual"),
            status=str(payload.get("status") or "queued"),
            display_name=str(payload.get("displayName") or payload.get("name") or "下载任务"),
            remote_ref=_json_text(payload.get("remoteRef", {})),
            save_path=save_path,
            file_path=str(payload["filePath"]) if payload.get("filePath") is not None else None,
            error_message=str(payload["errorMessage"]) if payload.get("errorMessage") is not None else None,
            progress=float(payload.get("progress") if payload.get("progress") is not None else 0),
        ),
    ).to_legacy_dict()
    _save_system_setting(db, "library.lastDownloadTargetPath", save_path)
    db.commit()
    _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="created", target_type="downloadTask", target_id=task.get("id"), message=f"创建下载任务：{task.get('displayName')}", metadata={"status": task.get("status"), "type": task.get("type")})
    return ok({"task": task, "autoImport": _enabled_monitor_folder_for_path(db, target_dir) is not None}, status_code=201)


@router.get("/download-tasks/{task_id}")
def get_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadTaskResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    return ok({"task": task})


@router.delete("/download-tasks/{task_id}")
def delete_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DeletedDownloadTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    deleted = delete_download_task_command(db, task_id)
    if deleted:
        _record_system_event(db, level="warning", source="download", actor_type="admin", actor_id=user.id, action="deleted", target_type="downloadTask", target_id=task_id, message=f"删除下载任务：{(task or {}).get('displayName') or task_id}", metadata={"status": (task or {}).get("status")})
    return ok({"deleted": deleted, "id": task_id})


@router.put("/download-tasks/{task_id}")
async def update_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    allowed = {"type", "status", "displayName", "savePath", "filePath", "errorMessage", "progress"}
    values = {key: value for key, value in payload.items() if key in allowed}
    if "remoteRef" in payload:
        values["remoteRef"] = _json_text(payload["remoteRef"])
    task_dto = update_download_task_command(
        db,
        task_id,
        UpdateDownloadTask(
            task_type=str(values["type"]) if "type" in values and values["type"] is not None else None,
            status=str(values["status"]) if "status" in values and values["status"] is not None else None,
            display_name=str(values["displayName"]) if "displayName" in values and values["displayName"] is not None else None,
            save_path=str(values["savePath"]) if "savePath" in values and values["savePath"] is not None else None,
            file_path=str(values["filePath"]) if "filePath" in values and values["filePath"] is not None else None,
            error_message=str(values["errorMessage"]) if "errorMessage" in values and values["errorMessage"] is not None else None,
            progress=float(values["progress"]) if "progress" in values and values["progress"] is not None else None,
            remote_ref=str(values["remoteRef"]) if "remoteRef" in values and values["remoteRef"] is not None else None,
            changed_fields=frozenset(values),
        ),
    )
    if task_dto is None:
        return fail("下载任务不存在", status_code=404)
    task = task_dto.to_legacy_dict()
    _record_system_event(db, level="error" if task.get("status") == "failed" else "info", source="download", actor_type="admin", actor_id=user.id, action="updated", target_type="downloadTask", target_id=task_id, message=f"更新下载任务：{task.get('displayName')}", metadata={"changes": values, "status": task.get("status"), "errorMessage": task.get("errorMessage")})
    return ok({"task": task})


@router.post("/download-tasks/{task_id}/start")
@router.post("/download-tasks/{task_id}/retry")
@router.post("/download-tasks/{task_id}/cancel")
@router.post("/download-tasks/{task_id}/import")
def mutate_download_task(task_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DownloadTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    action = request.url.path.rsplit("/", 1)[-1]
    task_dto = get_download_task_query(db, task_id)
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    if action in {"start", "retry"}:
        if action == "retry":
            if task.get("status") not in {"queued", "failed", "cancelled", "PENDING", "FAILED", "CANCELLED"}:
                return fail("只有等待中、失败或已取消的任务可以重新排队", status_code=400)
            updated = update_download_task_command(
                db,
                task_id,
                UpdateDownloadTask(
                    status="queued",
                    progress=0,
                    error_message=None,
                    changed_fields=frozenset({"status", "progress", "errorMessage"}),
                ),
            )
            task = updated.to_legacy_dict() if updated is not None else task
            _record_system_event(db, level="info", source="download", actor_type="admin", actor_id=user.id, action="retry", target_type="downloadTask", target_id=task_id, message=f"重新排队下载任务：{task.get('displayName')}", metadata={"status": task.get("status")})
            return ok({"task": task, "action": action})
        if task.get("status") not in {"queued", "failed", "PENDING", "FAILED"}:
            return fail("只有等待中或失败的任务可以开始下载", status_code=400)
        result = execute_download_task(db, settings, task_id)
        _record_system_event(db, level="error" if result.task.get("status") == "failed" else "info", source="download", actor_type="admin", actor_id=user.id, action="start", target_type="downloadTask", target_id=task_id, message=f"执行下载任务：{result.task.get('displayName')}", metadata={"status": result.task.get("status"), "errorMessage": result.task.get("errorMessage"), "filePath": result.task.get("filePath")})
        return ok({"task": result.task, "action": action})
    if action == "cancel":
        updated = update_download_task_command(
            db,
            task_id,
            UpdateDownloadTask(
                status="cancelled",
                changed_fields=frozenset({"status"}),
            ),
        )
        task = updated.to_legacy_dict() if updated is not None else task
        _record_system_event(db, level="warning", source="download", actor_type="admin", actor_id=user.id, action="cancelled", target_type="downloadTask", target_id=task_id, message=f"取消下载任务：{task.get('displayName')}", metadata={"status": task.get("status")})
        return ok({"task": task, "action": action})
    return fail("下载文件会由监控文件夹自动识别入库，无需手动导入", status_code=400)
