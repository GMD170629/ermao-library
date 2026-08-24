"""Read HTTP adapters for libraries and the target import queue."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.imports import (
    continue_library_import,
    get_import_task,
    get_library,
    get_library_by_root_path,
    library_has_topology,
    list_import_tasks_page,
    list_libraries,
    list_library_access_user_ids,
    persist_import_library_create,
    persist_import_library_delete,
    persist_import_library_update,
)
from app.bootstrap.system import get_setting
from app.contracts.http_errors import ErrorResponses
from app.core.authorization import (
    authorization_context,
    can_access_library,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.models.common import cuid
from app.modules.imports.application.library_commands import (
    PreparedLibraryCreate,
    PreparedLibraryDelete,
    PreparedLibraryUpdate,
    prepare_library_update_values,
)
from app.modules.imports.application.library_paths import (
    LibraryPathError,
    library_directory_tree_node,
    resolve_library_root_path,
)
from app.modules.imports.presentation.path_helpers import enabled_library_for_path
from app.modules.imports.presentation.schemas import (
    CreateLibraryRequest,
    DeletedLibraryResponse,
    ImportBadRequestError,
    ImportConflictError,
    ImportForbiddenError,
    ImportNotFoundError,
    LibrariesResponse,
    LibraryDirectoryResponse,
    LibraryImportTaskDetailResponse,
    LibraryImportTaskListResponse,
    LibraryResponse,
    ParsedReleaseTitleResponse,
    ParseReleaseTitleRequest,
    UpdateLibraryRequest,
)
from app.modules.imports.presentation.writes import router as writes_router
from app.modules.imports.public import parse_release_title
from app.modules.library.domain.layout import LibraryOrganizationMode
from app.schemas.responses import fail, ok
from app.services.system_events import prepare_system_event

router = APIRouter(tags=["imports"], route_class=TypedContractRoute)
router.include_router(writes_router)


def _now() -> datetime:
    return datetime.now(UTC)


def _auth(
    db: Session, request: Request, settings: Settings
) -> tuple[User | None, Response | None]:
    return require_user(db, request, settings)


def _system_setting_value(db: Session, key: str) -> str | None:
    parsed = get_setting(db, key)
    return str(parsed).strip() if parsed is not None and str(parsed).strip() else None


@router.get("/libraries", response_model=LibrariesResponse)
def list_library_roots(
    request: Request,
    purpose: Literal["upload"] | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibrariesResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    folders = list_libraries(db)
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


@router.get(
    "/libraries/{library_id}/import-tasks", response_model=LibraryImportTaskListResponse
)
def list_library_import_tasks(
    library_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
    state: Literal["ALL", "QUEUED", "RUNNING", "SUCCEEDED", "FAILED"] | None = Query(
        default=None
    ),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryImportTaskListResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if (
        user is None
        or get_library(db, library_id) is None
        or not can_access_library(db, user, library_id)
    ):
        return fail("书库不存在或无权访问", status_code=404, code="LIBRARY_NOT_FOUND")

    context = authorization_context(db, user)
    tasks, total, summary = list_import_tasks_page(
        db,
        context,
        page=page,
        page_size=page_size,
        library_id=library_id,
        state=state,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    normalized_page = min(max(1, page), total_pages)
    return ok(
        {
            "tasks": tasks,
            "page": normalized_page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
            "queued": summary["queued"],
            "running": summary["running"],
            "completed": summary["completed"],
            "failed": summary["failed"],
        }
    )


@router.get(
    "/library-import-tasks/{task_id}", response_model=LibraryImportTaskDetailResponse
)
def get_library_import_task(
    task_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryImportTaskDetailResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        return fail("任务不存在", status_code=404, code="IMPORT_TASK_NOT_FOUND")

    task = get_import_task(db, task_id, authorization_context(db, user))
    if task is None:
        return fail("任务不存在", status_code=404, code="IMPORT_TASK_NOT_FOUND")
    return ok({"task": task})


@router.get("/libraries/tree", response_model=LibraryDirectoryResponse)
def library_tree(
    request: Request,
    path: str | None = None,
    purpose: Literal["upload"] | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LibraryDirectoryResponse | Response:
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
    node, error, status_code = library_directory_tree_node(path)
    if error:
        return fail(error, status_code=status_code)
    return ok({"node": node})


@router.post("/libraries", response_model=LibraryResponse)
def create_library(
    payload: CreateLibraryRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    LibraryResponse | Response,
    ErrorResponses(
        ImportBadRequestError,
        ImportConflictError,
        ImportForbiddenError,
        ImportNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        return fail("当前用户无权管理书库", status_code=403)
    try:
        root_path = str(resolve_library_root_path(payload.root_path))
    except LibraryPathError as exc:
        return fail(str(exc), status_code=exc.status_code, code=exc.code)
    if get_library_by_root_path(db, root_path) is not None:
        return fail("书库路径已存在", status_code=409, details={"rootPath": root_path})

    library_id = cuid()
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
    if payload.enabled:
        continue_library_import(db, library_id)
    return ok({"library": get_library(db, library_id) or library}, status_code=201)


@router.patch("/libraries/{library_id}", response_model=LibraryResponse)
def update_library(
    library_id: str,
    payload: UpdateLibraryRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Annotated[
    LibraryResponse | Response,
    ErrorResponses(
        ImportBadRequestError,
        ImportConflictError,
        ImportForbiddenError,
        ImportNotFoundError,
    ),
]:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        return fail("当前用户无权管理书库", status_code=403)

    existing = get_library(db, library_id)
    if existing is None:
        return fail("书库不存在", status_code=404, code="LIBRARY_NOT_FOUND")
    values = payload.model_dump(by_alias=True, exclude_unset=True)
    if "organizationMode" in values and values["organizationMode"] is not None:
        values["organizationMode"] = LibraryOrganizationMode(
            values["organizationMode"]
        ).value
    structural_change = (
        "rootPath" in values and values["rootPath"] != existing.get("rootPath")
    ) or (
        "organizationMode" in values
        and values["organizationMode"] != existing.get("organizationMode")
    )
    if structural_change and library_has_topology(db, library_id):
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
        if get_library_by_root_path(db, root_path, exclude_id=library_id) is not None:
            return fail("书库路径已存在", status_code=409)
        values["rootPath"] = root_path
    was_enabled = bool(existing.get("enabled"))
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
        try:
            persist_import_library_update(
                db,
                PreparedLibraryUpdate(
                    library_id,
                    prepare_library_update_values(values),
                    prepared_event,
                ),
            )
        except IntegrityError:
            return fail("书库路径已存在", status_code=409)
    updated = get_library(db, library_id) or existing
    if bool(updated.get("enabled")) and not was_enabled:
        continue_library_import(db, library_id)
    return ok({"library": updated})


@router.delete("/libraries/{library_id}", response_model=DeletedLibraryResponse)
def delete_library(
    library_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedLibraryResponse | Response:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if user is None:
        return fail("当前用户无权管理书库", status_code=403)
    existing = get_library(db, library_id)
    if existing is None:
        return fail("书库不存在", status_code=404, code="LIBRARY_NOT_FOUND")
    affected_user_ids = list_library_access_user_ids(db, library_id)
    checkpoint_at = _now()
    prepared_event = prepare_system_event(
        level="warning",
        source="library",
        actor_type="admin",
        actor_id=user.id,
        action="deleted",
        target_type="library",
        target_id=library_id,
        message=f"删除书库：{existing.get('name') or library_id}",
        metadata={
            "rootPath": existing.get("rootPath"),
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


def _parsed_release_title(title: str) -> dict[str, object]:
    volume_info = parse_release_title(title)
    chapter = re.search(
        r"(?:ch(?:apter)?\.?|第)\s*(\d+(?:\.\d+)?)\s*(?:话|章|ch)?",
        title,
        flags=re.IGNORECASE,
    )
    return {
        "parsed": {
            "title": title,
            "volume": volume_info.volume_index if volume_info else None,
            "chapter": float(chapter.group(1)) if chapter else None,
        }
    }


@router.get("/tracking/release-title-parser", response_model=ParsedReleaseTitleResponse)
def release_title_parser_get(
    request: Request,
    title: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ParsedReleaseTitleResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok(_parsed_release_title(title))


@router.post(
    "/tracking/release-title-parser", response_model=ParsedReleaseTitleResponse
)
def release_title_parser(
    request: Request,
    payload: Annotated[ParseReleaseTitleRequest | None, Body()] = None,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ParsedReleaseTitleResponse | Response:
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    return ok(_parsed_release_title(payload.title if payload is not None else ""))


__all__ = ["router"]
