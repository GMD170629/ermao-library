"""Imports HTTP surface: monitor folders and import-task reads."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import import_http_store
from app.bootstrap.system import get_setting, record_system_event
from app.core.authorization import authorization_context, can_access_monitor_folder
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.presentation.writes import router as writes_router
from app.modules.imports.presentation.schemas import (
    DeletedMonitorFolderResponse,
    MonitorDirectoryResponse,
    MonitorFolderResponse,
    MonitorFoldersResponse,
    ParsedReleaseTitleResponse,
    ImportLogsResponse,
    ImportTaskResponse,
    ImportTasksResponse,
)
from app.modules.imports.presentation.mappers import (
    import_task_view,
    monitor_directory_tree_node,
    normalize_monitor_root_path,
)
from app.modules.imports.public import (
    parse_release_title,
    reset_failed_import_checkpoint,
)
from app.schemas.responses import fail, ok

router = APIRouter(tags=["imports"], route_class=TypedContractRoute)
router.include_router(writes_router)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _system_setting_value(db: Session, key: str) -> str | None:
    parsed = get_setting(db, key)
    return str(parsed).strip() if parsed is not None and str(parsed).strip() else None


def _visible_import_task_or_none(
    db: Session, user: User, task_id: str
) -> dict[str, Any] | None:
    task = import_http_store.get_import_task(db, task_id)
    if task is None or not can_access_monitor_folder(
        db, user, task.get("monitorFolderId")
    ):
        return None
    return task


@router.get("/monitor-folders")
def list_monitor_folders(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MonitorFoldersResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    folders = import_http_store.list_monitor_folders(db)
    return ok(
        {
            "folders": folders,
            "monitorRoot": str(settings.resolved_monitor_root.resolve())
            if settings.resolved_monitor_root
            else None,
            "lastUploadTargetPath": _system_setting_value(
                db, "library.lastUploadTargetPath"
            ),
            "lastDownloadTargetPath": _system_setting_value(
                db, "library.lastDownloadTargetPath"
            ),
        }
    )


@router.get("/monitor-folders/tree")
def monitor_folder_tree(
    request: Request,
    path: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MonitorDirectoryResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    node, error, status_code = monitor_directory_tree_node(settings, path)
    if error:
        return fail(error, status_code=status_code)
    return ok(
        {
            "node": node,
            "monitorRoot": str(settings.resolved_monitor_root.resolve())
            if settings.resolved_monitor_root
            else None,
        }
    )


@router.post("/monitor-folders")
async def create_monitor_folder(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MonitorFolderResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    root_path = normalize_monitor_root_path(payload.get("rootPath"))
    if not root_path:
        return fail("请填写监控文件夹路径", status_code=400)
    if import_http_store.get_monitor_folder_by_root_path(db, root_path):
        return fail(
            "监控文件夹路径已存在", status_code=409, details={"rootPath": root_path}
        )
    if payload.get("shelfId"):
        return fail(
            "监控文件夹不再绑定全局书架，请创建个人来源文件夹智能书架",
            status_code=400,
            code="MONITOR_FOLDER_SHELF_RETIRED",
        )
    raw_min_file_size = payload.get("minFileSizeBytes")
    try:
        min_file_size_bytes = int(
            10240 if raw_min_file_size is None else raw_min_file_size
        )
    except (TypeError, ValueError):
        return fail("最小文件大小必须是非负整数", status_code=400)
    if min_file_size_bytes < 0:
        return fail("最小文件大小必须是非负整数", status_code=400)
    try:
        folder = import_http_store.create_monitor_folder(
            db,
            {
                "id": f"py_{time_ns()}",
                "name": payload.get("name") or Path(root_path).name or "监控文件夹",
                "rootPath": root_path,
                "shelfId": None,
                "enabled": bool(payload.get("enabled", True)),
                "ignorePatterns": payload.get("ignorePatterns"),
                "ignoreHidden": bool(payload.get("ignoreHidden", True)),
                "minFileSizeBytes": min_file_size_bytes,
                "description": payload.get("description"),
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
    except IntegrityError:
        reset_failed_import_checkpoint(db)
        return fail(
            "监控文件夹路径已存在", status_code=409, details={"rootPath": root_path}
        )
    record_system_event(
        db,
        level="info",
        source="folder",
        actor_type="admin",
        actor_id=user.id,
        action="created",
        target_type="monitorFolder",
        target_id=folder.get("id"),
        message=f"新增来源目录：{folder.get('name')}",
        metadata={"rootPath": root_path},
        commit=True,
        prune=True,
    )
    return ok({"folder": folder}, status_code=201)


@router.put("/monitor-folders/{folder_id}")
@router.patch("/monitor-folders/{folder_id}")
async def update_monitor_folder(
    folder_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MonitorFolderResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    if payload.get("shelfId"):
        return fail(
            "监控文件夹不再绑定全局书架，请创建个人来源文件夹智能书架",
            status_code=400,
            code="MONITOR_FOLDER_SHELF_RETIRED",
        )
    mapping = {
        "rootPath": "rootPath",
        "minFileSizeBytes": "minFileSizeBytes",
        "ignorePatterns": "ignorePatterns",
        "ignoreHidden": "ignoreHidden",
        "enabled": "enabled",
        "name": "name",
        "description": "description",
    }
    values = {mapping[key]: value for key, value in payload.items() if key in mapping}
    existing = import_http_store.get_monitor_folder(db, folder_id)
    if not existing:
        return fail("监控文件夹不存在", status_code=404)
    if "rootPath" in values:
        root_path = normalize_monitor_root_path(values["rootPath"])
        if not root_path:
            return fail("请填写监控文件夹路径", status_code=400)
        if import_http_store.get_monitor_folder_by_root_path(
            db, root_path, exclude_id=folder_id
        ):
            return fail(
                "监控文件夹路径已存在", status_code=409, details={"rootPath": root_path}
            )
        values["rootPath"] = root_path
    if "minFileSizeBytes" in values:
        try:
            values["minFileSizeBytes"] = int(values["minFileSizeBytes"])
        except (TypeError, ValueError):
            return fail("最小文件大小必须是非负整数", status_code=400)
        if values["minFileSizeBytes"] < 0:
            return fail("最小文件大小必须是非负整数", status_code=400)
    if values:
        values["updatedAt"] = _now()
    try:
        folder = import_http_store.update_monitor_folder(db, folder_id, values)
    except IntegrityError:
        reset_failed_import_checkpoint(db)
        return fail(
            "监控文件夹路径已存在",
            status_code=409,
            details={"rootPath": values.get("rootPath")},
        )
    if values:
        record_system_event(
            db,
            level="info",
            source="folder",
            actor_type="admin",
            actor_id=user.id,
            action="updated",
            target_type="monitorFolder",
            target_id=folder_id,
            message=f"更新来源目录：{(folder or existing).get('name')}",
            metadata={
                "changes": values,
                "rootPath": (folder or existing).get("rootPath"),
            },
            commit=True,
            prune=True,
        )
    return ok({"folder": folder})


@router.delete("/monitor-folders/{folder_id}")
def delete_monitor_folder(
    folder_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedMonitorFolderResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    existing = import_http_store.get_monitor_folder(db, folder_id)
    deleted, affected_user_ids = import_http_store.delete_monitor_folder(
        db, folder_id, updated_at=_now()
    )
    if deleted:
        record_system_event(
            db,
            level="warning",
            source="folder",
            actor_type="admin",
            actor_id=user.id,
            action="deleted",
            target_type="monitorFolder",
            target_id=folder_id,
            message=f"删除来源目录：{(existing or {}).get('name') or folder_id}",
            metadata={
                "rootPath": (existing or {}).get("rootPath"),
                "authorizationInvalidatedFor": len(affected_user_ids),
            },
            commit=True,
            prune=True,
        )
    return ok({"deleted": deleted, "id": folder_id})


@router.get("/import-tasks")
def list_import_tasks(
    request: Request,
    page: int = 1,
    pageSize: int = 10,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportTasksResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    page = max(1, page)
    page_size = min(50, max(1, pageSize))
    context = authorization_context(db, user)
    normalized_status = str(status or "").strip().upper()
    if normalized_status and normalized_status != "ALL":
        if normalized_status not in {"PENDING", "PARSING", "COMPLETED", "FAILED"}:
            return fail("导入状态无效", status_code=400)
    tasks, total, summary = import_http_store.list_import_tasks_page(
        db,
        context,
        page=page,
        page_size=page_size,
        status=normalized_status or None,
        keyword=keyword,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    views = [import_task_view(db, task, log_limit=20) for task in tasks]
    return ok(
        {
            "tasks": views,
            "summary": summary,
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
        }
    )


@router.get("/import-tasks/{task_id}")
def get_import_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportTaskResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    task = _visible_import_task_or_none(db, user, task_id)
    if not task:
        return fail("导入任务不存在", status_code=404)
    return ok({"task": import_task_view(db, task, log_limit=100)})


@router.get("/import-tasks/{task_id}/logs")
def get_import_logs(
    task_id: str,
    request: Request,
    page: int = 1,
    pageSize: int = 100,
    level: str | None = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportLogsResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if _visible_import_task_or_none(db, user, task_id) is None:
        return fail("导入任务不存在", status_code=404)
    page = max(1, page)
    page_size = min(200, max(1, pageSize))
    logs, total = import_http_store.list_import_logs(
        db,
        task_id,
        limit=page_size,
        offset=(page - 1) * page_size,
        level=level,
    )
    from app.modules.imports.presentation.mappers import serialize_import_log

    return ok(
        {
            "logs": [serialize_import_log(log) for log in logs],
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": max(1, (total + page_size - 1) // page_size),
        }
    )


@router.get("/tracking/release-title-parser")
def release_title_parser_get(
    request: Request,
    title: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ParsedReleaseTitleResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    volume_info = parse_release_title(title)
    chapter = re.search(
        r"(?:ch(?:apter)?\.?|第)\s*(\d+(?:\.\d+)?)\s*(?:话|章|ch)?",
        title,
        flags=re.IGNORECASE,
    )
    return ok(
        {
            "parsed": {
                "title": title,
                "volume": volume_info.series_index if volume_info else None,
                "chapter": float(chapter.group(1)) if chapter else None,
            }
        }
    )


@router.post("/tracking/release-title-parser")
async def release_title_parser(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ParsedReleaseTitleResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    title = str(payload.get("title") or "")
    volume_info = parse_release_title(title)
    chapter = re.search(
        r"(?:ch(?:apter)?\.?|第)\s*(\d+(?:\.\d+)?)\s*(?:话|章|ch)?",
        title,
        flags=re.IGNORECASE,
    )
    return ok(
        {
            "parsed": {
                "title": title,
                "volume": volume_info.series_index if volume_info else None,
                "chapter": float(chapter.group(1)) if chapter else None,
            }
        }
    )
