"""Download-task HTTP surface."""

from __future__ import annotations

import json
from pathlib import Path
from time import time_ns
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.download import (
    create_download_task_command,
    delete_download_task_command,
    update_download_task_command,
)
from app.bootstrap.download import (
    get_download_task as get_download_task_query,
)
from app.bootstrap.download import (
    list_download_tasks as list_download_tasks_query,
)
from app.bootstrap.system import prepare_system_event
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.modules.download.presentation.schemas import (
    CreateDownloadTaskRequest,
    DeletedDownloadTaskResponse,
    DownloadTaskResponse,
    DownloadTasksResponse,
    UpdateDownloadTaskRequest,
)
from app.modules.download.public import CreateDownloadTask, UpdateDownloadTask
from app.modules.imports.public import (
    target_directory_from_path as _target_directory_from_path,
)
from app.schemas.responses import fail, ok
from app.services.download_executor import execute_download_task

router = APIRouter(tags=["download"], route_class=TypedContractRoute)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _enabled_library_for_path(
    folders: tuple[dict[str, Any], ...],
    target: Path,
) -> dict[str, Any] | None:
    from app.modules.imports.public import is_inside_path

    try:
        real_target = target.expanduser().resolve()
    except OSError:
        return None
    for folder in folders:
        try:
            root = Path(str(folder.get("rootPath") or "")).expanduser().resolve()
        except OSError:
            continue
        if root == real_target or is_inside_path(root, real_target):
            return folder
    return None


def _load_enabled_libraries(db: Session) -> tuple[dict[str, Any], ...]:
    from app.bootstrap.download import list_enabled_libraries

    folders = tuple(list_enabled_libraries(db))
    db.close()
    return folders


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except ValueError:
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@router.get("/download-tasks", response_model=DownloadTasksResponse)
def list_download_tasks(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadTasksResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    tasks = [
        task.to_legacy_dict() for task in list_download_tasks_query(db, limit=1000)
    ]
    folders = _load_enabled_libraries(db)
    return ok(
        {
            "tasks": [
                {
                    **task,
                    "remoteRef": _parse_json(
                        task.get("remoteRef"), task.get("remoteRef")
                    ),
                    "sourceName": None,
                    "autoImport": _enabled_library_for_path(
                        folders, Path(str(task.get("savePath") or ""))
                    )
                    is not None,
                }
                for task in tasks
            ]
        }
    )


@router.post("/download-tasks", response_model=DownloadTaskResponse)
async def create_download_task(
    request: Request,
    payload: Annotated[CreateDownloadTaskRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadTaskResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    actor_id = user.id
    db.close()
    if payload is None:
        return fail("下载任务参数格式不正确", status_code=400)
    values = payload.model_dump(by_alias=True, exclude_unset=True)
    try:
        target_dir = _target_directory_from_path(values.get("targetPath"), "下载")
    except ValueError as exc:
        return fail(str(exc), status_code=400)
    save_path = str(target_dir)
    progress_value = values.get("progress")
    progress = (
        float(progress_value) if isinstance(progress_value, (int, float, str)) else 0.0
    )
    command = CreateDownloadTask(
        id=f"py_{time_ns()}",
        source_id=str(values["sourceId"])
        if values.get("sourceId") is not None
        else None,
        search_record_id=str(values["searchRecordId"])
        if values.get("searchRecordId") is not None
        else None,
        book_id=str(values["bookId"]) if values.get("bookId") is not None else None,
        task_type=str(values.get("type") or "manual"),
        status=str(values.get("status") or "queued"),
        display_name=str(values.get("displayName") or values.get("name") or "下载任务"),
        remote_ref=_json_text(values.get("remoteRef", {})),
        save_path=save_path,
        file_path=str(values["filePath"])
        if values.get("filePath") is not None
        else None,
        error_message=str(values["errorMessage"])
        if values.get("errorMessage") is not None
        else None,
        progress=progress,
    )
    prepared_event = prepare_system_event(
        level="info",
        source="download",
        actor_type="admin",
        actor_id=actor_id,
        action="created",
        target_type="downloadTask",
        target_id=command.id,
        message=f"创建下载任务：{command.display_name}",
        metadata={"status": command.status, "type": command.task_type},
    )
    task = create_download_task_command(
        db,
        command,
        last_target_path=save_path,
        event=prepared_event,
    ).to_legacy_dict()
    folders = _load_enabled_libraries(db)
    return ok(
        {
            "task": task,
            "autoImport": _enabled_library_for_path(folders, target_dir) is not None,
        },
        status_code=201,
    )


@router.get("/download-tasks/{task_id}", response_model=DownloadTaskResponse)
def get_download_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadTaskResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task_dto = get_download_task_query(db, task_id)
    db.close()
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    return ok({"task": task})


@router.delete("/download-tasks/{task_id}", response_model=DeletedDownloadTaskResponse)
def delete_download_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedDownloadTaskResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    actor_id = user.id
    task_dto = get_download_task_query(db, task_id)
    db.close()
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    prepared_event = prepare_system_event(
        level="warning",
        source="download",
        actor_type="admin",
        actor_id=actor_id,
        action="deleted",
        target_type="downloadTask",
        target_id=task_id,
        message=f"删除下载任务：{(task or {}).get('displayName') or task_id}",
        metadata={"status": (task or {}).get("status")},
    )
    deleted = delete_download_task_command(db, task_id, event=prepared_event)
    return ok({"deleted": deleted, "id": task_id})


@router.put("/download-tasks/{task_id}", response_model=DownloadTaskResponse)
async def update_download_task(
    task_id: str,
    request: Request,
    payload: Annotated[UpdateDownloadTaskRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadTaskResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    actor_id = user.id
    db.close()
    if payload is None:
        return fail("下载任务参数格式不正确", status_code=400)
    payload_values = payload.model_dump(by_alias=True, exclude_unset=True)
    allowed = {
        "type",
        "status",
        "displayName",
        "savePath",
        "filePath",
        "errorMessage",
        "progress",
    }
    values = {key: value for key, value in payload_values.items() if key in allowed}
    if "remoteRef" in payload_values:
        values["remoteRef"] = _json_text(payload_values["remoteRef"])
    changes = UpdateDownloadTask(
        task_type=str(values["type"])
        if "type" in values and values["type"] is not None
        else None,
        status=str(values["status"])
        if "status" in values and values["status"] is not None
        else None,
        display_name=str(values["displayName"])
        if "displayName" in values and values["displayName"] is not None
        else None,
        save_path=str(values["savePath"])
        if "savePath" in values and values["savePath"] is not None
        else None,
        file_path=str(values["filePath"])
        if "filePath" in values and values["filePath"] is not None
        else None,
        error_message=str(values["errorMessage"])
        if "errorMessage" in values and values["errorMessage"] is not None
        else None,
        progress=float(values["progress"])
        if "progress" in values and values["progress"] is not None
        else None,
        remote_ref=str(values["remoteRef"])
        if "remoteRef" in values and values["remoteRef"] is not None
        else None,
        changed_fields=frozenset(values),
    )
    existing_dto = get_download_task_query(db, task_id)
    db.close()
    if existing_dto is None:
        return fail("下载任务不存在", status_code=404)
    existing = existing_dto.to_legacy_dict()
    next_display_name = str(values.get("displayName") or existing.get("displayName"))
    next_status = str(values.get("status") or existing.get("status"))
    prepared_event = prepare_system_event(
        level="error" if next_status == "failed" else "info",
        source="download",
        actor_type="admin",
        actor_id=actor_id,
        action="updated",
        target_type="downloadTask",
        target_id=task_id,
        message=f"更新下载任务：{next_display_name}",
        metadata={
            "changes": values,
            "status": next_status,
            "errorMessage": values.get("errorMessage", existing.get("errorMessage")),
        },
    )
    task_dto = update_download_task_command(db, task_id, changes, event=prepared_event)
    if task_dto is None:
        return fail("下载任务不存在", status_code=404)
    task = task_dto.to_legacy_dict()
    return ok({"task": task})


@router.post("/download-tasks/{task_id}/start", response_model=DownloadTaskResponse)
@router.post("/download-tasks/{task_id}/retry", response_model=DownloadTaskResponse)
@router.post("/download-tasks/{task_id}/cancel", response_model=DownloadTaskResponse)
@router.post("/download-tasks/{task_id}/import", response_model=DownloadTaskResponse)
def mutate_download_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DownloadTaskResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    actor_id = user.id
    action = request.url.path.rsplit("/", 1)[-1]
    task_dto = get_download_task_query(db, task_id)
    db.close()
    task = task_dto.to_legacy_dict() if task_dto is not None else None
    if not task:
        return fail("下载任务不存在", status_code=404)
    if action in {"start", "retry"}:
        if action == "retry":
            if task.get("status") not in {
                "queued",
                "failed",
                "cancelled",
                "PENDING",
                "FAILED",
                "CANCELLED",
            }:
                return fail(
                    "只有等待中、失败或已取消的任务可以重新排队", status_code=400
                )
            changes = UpdateDownloadTask(
                status="queued",
                progress=0,
                error_message=None,
                changed_fields=frozenset({"status", "progress", "errorMessage"}),
            )
            prepared_event = prepare_system_event(
                level="info",
                source="download",
                actor_type="admin",
                actor_id=actor_id,
                action="retry",
                target_type="downloadTask",
                target_id=task_id,
                message=f"重新排队下载任务：{task.get('displayName')}",
                metadata={"status": "queued"},
            )
            updated = update_download_task_command(
                db, task_id, changes, event=prepared_event
            )
            task = updated.to_legacy_dict() if updated is not None else task
            return ok({"task": task, "action": action})
        if task.get("status") not in {"queued", "failed", "PENDING", "FAILED"}:
            return fail("只有等待中或失败的任务可以开始下载", status_code=400)
        result = execute_download_task(db, settings, task_id)
        return ok({"task": result.task, "action": action})
    if action == "cancel":
        changes = UpdateDownloadTask(
            status="cancelled",
            changed_fields=frozenset({"status"}),
        )
        prepared_event = prepare_system_event(
            level="warning",
            source="download",
            actor_type="admin",
            actor_id=actor_id,
            action="cancelled",
            target_type="downloadTask",
            target_id=task_id,
            message=f"取消下载任务：{task.get('displayName')}",
            metadata={"status": "cancelled"},
        )
        updated = update_download_task_command(
            db, task_id, changes, event=prepared_event
        )
        task = updated.to_legacy_dict() if updated is not None else task
        return ok({"task": task, "action": action})
    return fail("下载文件会由书库自动识别入库，无需手动导入", status_code=400)
