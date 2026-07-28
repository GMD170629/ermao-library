"""Shelf HTTP surface."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.shelf import shelf_store
from app.core.authorization import authorization_context, can_access_work
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.library.public import bookshelf_item_view, get_work
from app.modules.shelf.public import execute_shelf_write
from app.modules.shelf.presentation.schemas import (
    DeletedShelfResponse,
    ShelfResponse,
    ShelvesResponse,
)
from app.schemas.responses import fail, ok
from app.services.library_filters import normalize_filter_rules
from app.services.library_management import smart_shelf_work_ids

router = APIRouter(tags=["shelf"], route_class=TypedContractRoute)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


def _has_table(db: Session, table: str) -> bool:
    try:
        return table in inspect(db.connection()).get_table_names()
    except Exception:
        return False


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


def _bookshelf_item_view(work: dict[str, Any]) -> dict[str, Any]:
    return bookshelf_item_view(work)


def _get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    return get_work(db, work_id)

@router.get("/shelves")
def list_shelves(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> ShelvesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelves = shelf_store.list_shelves_for_user(db, user.id)
    return ok({"shelves": [_shelf_summary_view(db, shelf, user) for shelf in shelves]})


def _owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    return shelf_store.get_owned_shelf(db, shelf_id, user_id)


def _shelf_work_ids(db: Session, shelf: dict[str, Any], user: User) -> list[str]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    rules = _parse_json(shelf.get("rulesJson"), {})
    work_ids = (
        smart_shelf_work_ids(db, rules, user.id)
        if kind == "SMART"
        else shelf_store.list_static_shelf_work_ids(db, str(shelf["id"]))
    )
    if not work_ids:
        return []
    context = authorization_context(db, user)
    return shelf_store.filter_visible_work_ids(db, work_ids, context)


def _shelf_book_views(db: Session, work_ids: list[str]) -> list[dict[str, Any]]:
    works = shelf_store.list_work_cards(db, work_ids)
    return [_bookshelf_item_view(work) for work in works]


def _shelf_base_view(shelf: dict[str, Any], work_ids: list[str]) -> dict[str, Any]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    return {
        **shelf,
        "kind": kind,
        "rules": _parse_json(shelf.get("rulesJson"), {}),
        "bookCount": len(work_ids),
    }


def _shelf_summary_view(db: Session, shelf: dict[str, Any], user: User) -> dict[str, Any]:
    work_ids = _shelf_work_ids(db, shelf, user)
    return {
        **_shelf_base_view(shelf, work_ids),
        "books": _shelf_book_views(db, work_ids[:3]),
    }


def _shelf_detail_view(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    page: int = 1,
    page_size: int = 24,
    include_book_ids: bool = True,
) -> dict[str, Any]:
    work_ids = _shelf_work_ids(db, shelf, user)
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = len(work_ids)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_ids = work_ids[start:start + page_size]
    result = {
        **_shelf_base_view(shelf, work_ids),
        "books": _shelf_book_views(db, page_ids),
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }
    if include_book_ids:
        result["bookIds"] = work_ids
    return result


def _normalized_smart_shelf_rules(value: Any) -> tuple[dict[str, Any], str | None]:
    if value is None:
        return {}, None
    if not isinstance(value, dict):
        return {}, "智能书架规则格式不正确"
    rules: dict[str, Any] = {}
    search = str(value.get("search") or "").strip()
    if search:
        rules["search"] = search[:200]
    statuses = [str(item).upper() for item in value.get("statuses") or []]
    if any(item not in {"UNREAD", "READING", "FINISHED"} for item in statuses):
        return {}, "阅读状态规则无效"
    if statuses:
        rules["statuses"] = list(dict.fromkeys(statuses))
    media_kinds = [str(item).upper() for item in value.get("mediaKinds") or []]
    if any(item not in {"EBOOK", "COMIC", "AUDIOBOOK"} for item in media_kinds):
        return {}, "媒介类型规则无效"
    if media_kinds:
        rules["mediaKinds"] = list(dict.fromkeys(media_kinds))
    for key in ("tags", "authors", "publishers"):
        values = [str(item).strip() for item in value.get(key) or [] if str(item).strip()]
        if values:
            rules[key] = list(dict.fromkeys(values))[:100]
    dynamic_rules, dynamic_error = normalize_filter_rules(
        {"combinator": value.get("combinator", "ALL"), "conditions": value.get("conditions") or []}
    )
    if dynamic_error:
        return {}, dynamic_error
    if dynamic_rules["conditions"]:
        rules.update(dynamic_rules)
    included_work_ids = [
        str(item).strip()
        for item in value.get("includedWorkIds") or []
        if str(item).strip()
    ]
    if included_work_ids:
        rules["includedWorkIds"] = list(dict.fromkeys(included_work_ids))[:500]
    return rules, None


def _normalized_shelf_work_ids(db: Session, value: Any, user: User) -> tuple[list[str], str | None]:
    if not isinstance(value, list):
        return [], "图书列表格式不正确"
    work_ids: list[str] = []
    for item in value:
        work_id = str(item or "").strip()
        if work_id and work_id not in work_ids:
            work_ids.append(work_id)
    if not work_ids:
        return [], None
    if not _has_table(db, "LibraryWork"):
        return [], "选择的图书不存在，请刷新后重试"
    existing_ids = {work_id for work_id in work_ids if _get_work(db, work_id)}
    if missing := [work_id for work_id in work_ids if work_id not in existing_ids]:
        return [], f"有 {len(missing)} 本图书已不存在，请刷新后重试"
    inaccessible = [work_id for work_id in work_ids if not can_access_work(db, user, work_id)]
    if inaccessible:
        return [], "选择的图书不存在，请刷新后重试"
    return work_ids, None


def _replace_shelf_works(db: Session, shelf_id: str, work_ids: list[str]) -> None:
    shelf_store.replace_shelf_works(db, shelf_id, work_ids, now=_now())


@router.get("/shelves/{shelf_id}")
def get_shelf(
    shelf_id: str,
    request: Request,
    page: int = 1,
    pageSize: int = 24,
    includeBookIds: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    return ok({
        "shelf": _shelf_detail_view(
            db,
            shelf,
            user,
            page=page,
            page_size=pageSize,
            include_book_ids=includeBookIds,
        )
    })


@router.post("/shelves")
async def create_shelf(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> ShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    name = str(payload.get("name") or "").strip()
    if not name:
        return fail("请填写书架名称", status_code=400)
    kind = str(payload.get("kind") or "STATIC").strip().upper()
    if kind not in {"STATIC", "SMART"}:
        return fail("书架类型无效", status_code=400)
    rules, rules_error = _normalized_smart_shelf_rules(payload.get("rules"))
    if rules_error:
        return fail(rules_error, status_code=400)
    work_ids, work_error = _normalized_shelf_work_ids(db, payload.get("bookIds", payload.get("workIds", [])), user)
    if work_error:
        return fail(work_error, status_code=400)
    def create_operation() -> dict[str, Any]:
        shelf = shelf_store.create_shelf(
            db,
            {
                "id": f"py_{time_ns()}",
                "ownerUserId": user.id,
                "name": name,
                "description": str(payload.get("description") or "").strip()
                or None,
                "kind": kind,
                "rulesJson": _json_text(rules),
                "pinned": bool(payload.get("pinned")),
                "createdAt": _now(),
                "updatedAt": _now(),
            },
        )
        if kind == "STATIC":
            _replace_shelf_works(db, shelf["id"], work_ids)
        return shelf

    shelf = execute_shelf_write(db, create_operation)
    return ok({"shelf": _shelf_detail_view(db, shelf, user)}, status_code=201)


@router.patch("/shelves/{shelf_id}")
async def update_shelf(shelf_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> ShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = await request.json()
    values = {key: payload[key] for key in ("name", "description", "pinned") if key in payload}
    if "name" in values:
        values["name"] = str(values["name"] or "").strip()
        if not values["name"]:
            return fail("请填写书架名称", status_code=400)
    if "description" in values:
        values["description"] = str(values["description"] or "").strip() or None
    existing_shelf = _owned_shelf(db, shelf_id, user.id)
    if not existing_shelf:
        return fail("书架不存在", status_code=404)
    kind = str(payload.get("kind") or existing_shelf.get("kind") or "STATIC").strip().upper()
    if kind not in {"STATIC", "SMART"}:
        return fail("书架类型无效", status_code=400)
    rules, rules_error = _normalized_smart_shelf_rules(payload.get("rules", _parse_json(existing_shelf.get("rulesJson"), {})))
    if rules_error:
        return fail(rules_error, status_code=400)
    values.update({"kind": kind, "rulesJson": _json_text(rules)})
    works = payload.get("bookIds", payload.get("workIds"))
    work_ids: list[str] | None = None
    if works is not None:
        work_ids, work_error = _normalized_shelf_work_ids(db, works, user)
        if work_error:
            return fail(work_error, status_code=400)
    values["updatedAt"] = _now()
    def update_operation() -> dict[str, Any] | None:
        shelf = shelf_store.update_shelf(db, shelf_id, values)
        if shelf is None:
            return None
        if work_ids is not None and kind == "STATIC":
            _replace_shelf_works(db, shelf_id, work_ids)
        elif (
            kind == "SMART"
            and str(existing_shelf.get("kind") or "STATIC").upper() != "SMART"
        ):
            _replace_shelf_works(db, shelf_id, [])
        return shelf

    shelf = execute_shelf_write(db, update_operation)
    if not shelf:
        return fail("书架不存在", status_code=404)
    return ok({"shelf": _shelf_detail_view(db, shelf, user)})


@router.delete("/shelves/{shelf_id}")
def delete_shelf(shelf_id: str, request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> DeletedShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    def delete_operation() -> bool:
        shelf_store.clear_monitor_folder_shelf_links(db, shelf_id, now=_now())
        return shelf_store.delete_shelf(db, shelf_id)

    deleted = execute_shelf_write(db, delete_operation)
    return ok({"deleted": deleted, "id": shelf_id})
