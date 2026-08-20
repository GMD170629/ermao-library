"""Imports HTTP surface: libraries and import-task reads."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, time_ns
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    import_http_store,
    persist_import_library_create,
    persist_import_library_delete,
    persist_import_library_update,
)
from app.bootstrap.system import get_setting
from app.core.authorization import authorization_context, can_access_library
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.imports.application.library_commands import (
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryUpdate,
    prepare_library_update_values,
)
from app.modules.imports.presentation.mappers import (
    LibraryPathError,
    import_task_view,
    library_directory_tree_node,
    resolve_library_root_path,
)
from app.modules.imports.presentation.path_helpers import (
    enabled_library_for_path,
)
from app.modules.imports.presentation.schemas import (
    CreateLibraryRequest,
    DeletedLibraryResponse,
    ImportLogsResponse,
    ImportTaskResponse,
    ImportTasksResponse,
    LibrariesResponse,
    LibraryDirectoryResponse,
    LibraryResponse,
    ParsedReleaseTitleResponse,
    ParseReleaseTitleRequest,
    UpdateLibraryRequest,
)
from app.modules.imports.presentation.writes import router as writes_router
from app.modules.imports.public import parse_release_title
from app.modules.library.domain.layout import LibraryOrganizationMode
from app.schemas.responses import fail, ok
from app.services.system_events import (
    prepare_system_event,
)

router = APIRouter(tags=["imports"], route_class=TypedContractRoute)
router.include_router(writes_router)
logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


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
    if task is None or not can_access_library(db, user, task.get("libraryId")):
        return None
    return task


@router.get("/libraries")
def list_libraries(
    request: Request,
    purpose: Literal["upload"] | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibrariesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    folders = import_http_store.list_libraries(db)
    if purpose == "upload" and user is not None:
        context = authorization_context(db, user)
        allowed_library_ids = set(context.library_ids)
        folders = [
            folder
            for folder in folders
            if bool(folder.get("enabled"))
            and (context.is_admin or str(folder.get("id") or "") in allowed_library_ids)
        ]
    return ok(
        {
            "libraries": folders,
            "lastUploadTargetPath": _system_setting_value(
                db, "library.lastUploadTargetPath"
            ),
            "lastDownloadTargetPath": _system_setting_value(
                db, "library.lastDownloadTargetPath"
            ),
        }
    )


@router.get("/libraries/tree")
def library_tree(
    request: Request,
    path: str | None = None,
    purpose: Literal["upload"] | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryDirectoryResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if purpose == "upload":
        library = enabled_library_for_path(db, Path(path)) if path else None
        library_id = str((library or {}).get("id") or "") or None
        if (
            library is None
            or user is None
            or not can_access_library(db, user, library_id)
        ):
            return fail(
                "目标文件夹不存在或无权访问",
                status_code=404,
                code="LIBRARY_NOT_FOUND",
            )
    db.close()
    node, error, status_code = library_directory_tree_node(path)
    if error:
        return fail(error, status_code=status_code)
    return ok(
        {
            "node": node,
        }
    )


@router.post("/libraries")
async def create_library(
    payload: CreateLibraryRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    try:
        root_path = str(resolve_library_root_path(payload.root_path))
    except LibraryPathError as exc:
        return fail(str(exc), status_code=exc.status_code, code=exc.code)
    existing_library = import_http_store.get_library_by_root_path(db, root_path)
    db.close()
    if existing_library:
        return fail("书库路径已存在", status_code=409, details={"rootPath": root_path})
    library_id = f"py_{time_ns()}"
    checkpoint_at = _now()
    library: dict[str, object] = {
        "id": library_id,
        "name": payload.name or Path(root_path).name or "书库",
        "rootPath": root_path,
        "organizationMode": payload.organization_mode.value,
        "enabled": payload.enabled,
        "ignorePatterns": payload.ignore_patterns,
        "ignoreHidden": payload.ignore_hidden,
        "minFileSizeBytes": payload.min_file_size_bytes,
        "description": payload.description,
        "createdAt": checkpoint_at,
        "updatedAt": checkpoint_at,
    }
    prepared_event = prepare_system_event(
        level="info",
        source="library",
        actor_type="admin",
        actor_id=user.id,
        action="created",
        target_type="library",
        target_id=library_id,
        message=f"新增书库：{library['name']}",
        metadata={"rootPath": root_path},
    )
    try:
        persist_import_library_create(
            db,
            PreparedLibraryCreate(library, prepared_event),
        )
    except IntegrityError:
        return fail("书库路径已存在", status_code=409, details={"rootPath": root_path})
    return ok({"library": library}, status_code=201)


@router.patch("/libraries/{library_id}")
async def update_library(
    library_id: str,
    payload: UpdateLibraryRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    values = payload.model_dump(by_alias=True, exclude_unset=True)
    if "organizationMode" in values and values["organizationMode"] is not None:
        values["organizationMode"] = LibraryOrganizationMode(
            values["organizationMode"]
        ).value
    existing = import_http_store.get_library(db, library_id)
    if not existing:
        return fail("书库不存在", status_code=404, code="LIBRARY_NOT_FOUND")
    structural_change = (
        "rootPath" in values and values["rootPath"] != existing.get("rootPath")
    ) or (
        "organizationMode" in values
        and values["organizationMode"] != existing.get("organizationMode")
    )
    if structural_change and import_http_store.library_has_topology(db, library_id):
        return fail(
            "书库已有目录拓扑，不能修改根路径或组织方式",
            status_code=409,
            code="LIBRARY_TOPOLOGY_LOCKED",
        )
    if "rootPath" in values:
        try:
            root_path = str(resolve_library_root_path(values["rootPath"]))
        except LibraryPathError as exc:
            return fail(str(exc), status_code=exc.status_code, code=exc.code)
        if import_http_store.get_library_by_root_path(
            db, root_path, exclude_id=library_id
        ):
            return fail(
                "书库路径已存在", status_code=409, details={"rootPath": root_path}
            )
        values["rootPath"] = root_path
    db.close()
    if values:
        values["updatedAt"] = _now()
        prepared_event = prepare_system_event(
            level="info",
            source="library",
            actor_type="admin",
            actor_id=user.id,
            action="updated",
            target_type="library",
            target_id=library_id,
            message=f"更新书库：{values.get('name') or existing.get('name')}",
            metadata={
                "changes": values,
                "rootPath": values.get("rootPath") or existing.get("rootPath"),
            },
        )
        prepared_values = prepare_library_update_values(values)
        try:
            persist_import_library_update(
                db,
                PreparedLibraryUpdate(
                    library_id,
                    prepared_values,
                    prepared_event,
                ),
            )
        except IntegrityError:
            return fail(
                "书库路径已存在",
                status_code=409,
                details={"rootPath": values.get("rootPath")},
            )
        library = import_http_store.get_library(db, library_id)
    else:
        library = existing
    return ok({"library": library})


@router.delete("/libraries/{library_id}")
def delete_library(
    library_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedLibraryResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    existing = import_http_store.get_library(db, library_id)
    affected_user_ids = import_http_store.list_library_access_user_ids(
        db,
        library_id,
    )
    db.close()
    checkpoint_at = _now()
    prepared_event = prepare_system_event(
        level="warning",
        source="library",
        actor_type="admin",
        actor_id=user.id,
        action="deleted",
        target_type="library",
        target_id=library_id,
        message=f"删除书库：{(existing or {}).get('name') or library_id}",
        metadata={
            "rootPath": (existing or {}).get("rootPath"),
            "authorizationInvalidatedFor": len(affected_user_ids),
        },
    )
    deleted = persist_import_library_delete(
        db,
        PreparedLibraryDelete(
            library_id,
            affected_user_ids,
            checkpoint_at,
            prepared_event,
        ),
    )
    return ok({"deleted": deleted, "id": library_id})


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
    started_at = perf_counter()
    tasks, total, summary = import_http_store.list_import_tasks_page(
        db,
        context,
        page=page,
        page_size=page_size,
        status=normalized_status or None,
        keyword=keyword,
    )
    queried_at = perf_counter()
    tasks = import_http_store.hydrate_import_task_page(db, tasks, log_limit=20)
    hydrated_at = perf_counter()
    db.close()
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    views = [import_task_view(db, task, log_limit=20) for task in tasks]
    mapped_at = perf_counter()
    logger.info(
        "import_tasks.page.loaded",
        extra={
            "event": "import_tasks.page.loaded",
            "actorId": user.id,
            "page": page,
            "pageSize": page_size,
            "resultCount": len(views),
            "queryElapsedMs": round((queried_at - started_at) * 1000, 2),
            "hydrateElapsedMs": round((hydrated_at - queried_at) * 1000, 2),
            "mapElapsedMs": round((mapped_at - hydrated_at) * 1000, 2),
            "elapsedMs": round((mapped_at - started_at) * 1000, 2),
        },
    )
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
    task = import_http_store.hydrate_import_task_page(db, [task], log_limit=100)[0]
    db.close()
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
    db.close()
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
    db.close()
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
                "volume": volume_info.volume_index if volume_info else None,
                "chapter": float(chapter.group(1)) if chapter else None,
            }
        }
    )


@router.post("/tracking/release-title-parser")
def release_title_parser(
    request: Request,
    payload: Annotated[ParseReleaseTitleRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ParsedReleaseTitleResponse:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    db.close()
    title = payload.title if payload is not None else ""
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
                "volume": volume_info.volume_index if volume_info else None,
                "chapter": float(chapter.group(1)) if chapter else None,
            }
        }
    )
