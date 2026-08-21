"""Shelf HTTP surface."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from time import time_ns
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.api.typed_route import TypedContractRoute
from app.bootstrap.library import bookshelf_items as get_bookshelf_items
from app.bootstrap.library import smart_shelf_book_ids
from app.bootstrap.shelf import shelf_store
from app.core.authorization import (
    AuthorizationContext,
    authorization_context,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import User
from app.modules.library.public import bookshelf_item_views, get_book
from app.modules.shelf.application import (
    ShelfReference,
    validate_collection_replacement,
    validate_member_replacement,
)
from app.modules.shelf.domain import (
    ShelfCollectionPolicyError,
    ShelfKind,
    validate_shelf_content,
)
from app.modules.shelf.presentation.schemas import (
    DeletedShelfResponse,
    ShelfResponse,
    ShelfWriteRequest,
    ShelvesResponse,
)
from app.modules.shelf.public import (
    CreateShelf,
    CreateShelfCommand,
    DeleteShelf,
    DeleteShelfCommand,
    UpdateShelf,
    UpdateShelfCommand,
)
from app.schemas.responses import fail, ok
from app.services.library_filters import normalize_filter_rules

router = APIRouter(tags=["shelf"], route_class=TypedContractRoute)

UNSUPPORTED_SMART_SHELF_FIELDS = frozenset(
    {"publishedYear", "publisher", "language", "isbn", "identifier"}
)


def _unsupported_rule_fields(rules: dict[str, Any]) -> list[str]:
    fields = {
        str(condition.get("field"))
        for condition in rules.get("conditions") or []
        if isinstance(condition, dict)
        and str(condition.get("field")) in UNSUPPORTED_SMART_SHELF_FIELDS
    }
    if rules.get("publishers"):
        fields.add("publisher")
    return sorted(fields)


def _now() -> datetime:
    return datetime.now(UTC)


def _auth(db: Session, request: Request, settings: Settings):
    return require_user(db, request, settings)


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


def _validated_shelf_payload(payload: ShelfWriteRequest) -> dict[str, Any]:
    return payload.model_dump(
        by_alias=True,
        exclude_none=True,
        exclude_unset=True,
    )


def _get_book(db: Session, book_id: str) -> dict[str, Any] | None:
    return get_book(db, book_id)


@router.get("/shelves")
def list_shelves(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShelvesResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelves = shelf_store.list_shelves_for_user(db, user.id)
    context = authorization_context(db, user)
    collection_ids_by_shelf_id = shelf_store.list_collection_ids_by_shelf_ids(
        db,
        [str(shelf["id"]) for shelf in shelves],
    )
    collection_member_count_by_id = shelf_store.collection_member_counts(
        db,
        [
            str(shelf["id"])
            for shelf in shelves
            if str(shelf.get("kind") or "").upper() == ShelfKind.COLLECTION
        ],
    )
    return ok(
        {
            "shelves": [
                _shelf_summary_view(
                    db,
                    shelf,
                    user,
                    collection_ids=collection_ids_by_shelf_id.get(
                        str(shelf["id"]),
                        [],
                    ),
                    collection_member_count=collection_member_count_by_id.get(
                        str(shelf["id"])
                    ),
                    context=context,
                )
                for shelf in shelves
            ]
        }
    )


def _owned_shelf(db: Session, shelf_id: str, user_id: str) -> dict[str, Any] | None:
    return shelf_store.get_owned_shelf(db, shelf_id, user_id)


def _shelf_book_ids(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    context: AuthorizationContext | None = None,
) -> list[str]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    if kind == ShelfKind.COLLECTION:
        return []
    rules = _parse_json(shelf.get("rulesJson"), {})
    if kind == "SMART" and _unsupported_rule_fields(rules):
        return []
    book_ids = (
        smart_shelf_book_ids(db, rules, user_id=user.id)
        if kind == "SMART"
        else shelf_store.list_static_shelf_book_ids(db, str(shelf["id"]))
    )
    if not book_ids:
        return []
    visibility = context or authorization_context(db, user)
    return shelf_store.filter_visible_book_ids(db, book_ids, visibility)


def _shelf_book_views(
    db: Session,
    book_ids: list[str],
    context: AuthorizationContext,
) -> list[dict[str, Any]]:
    summaries = get_bookshelf_items(db).execute(
        context=context,
        book_ids=tuple(book_ids),
    )
    return bookshelf_item_views(summaries)


def _shelf_base_view(shelf: dict[str, Any]) -> dict[str, Any]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    rules = _parse_json(shelf.get("rulesJson"), {})
    unsupported_fields = _unsupported_rule_fields(rules) if kind == "SMART" else []
    return {
        **shelf,
        "kind": kind,
        "rules": rules,
        "rulesStatus": "UNSUPPORTED" if unsupported_fields else "VALID",
        "unsupportedRuleFields": unsupported_fields,
    }


def _shelf_summary_view(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    collection_ids: list[str] | None = None,
    collection_member_count: int | None = None,
    context: AuthorizationContext | None = None,
) -> dict[str, Any]:
    kind = str(shelf.get("kind") or "STATIC").upper()
    if kind == ShelfKind.COLLECTION:
        return {
            **_shelf_base_view(shelf),
            "shelfCount": collection_member_count
            if collection_member_count is not None
            else len(shelf_store.list_member_shelf_ids(db, str(shelf["id"]))),
            "shelves": [],
        }
    if kind == "STATIC":
        book_ids, total = shelf_store.list_static_shelf_book_page(
            db,
            str(shelf["id"]),
            context or authorization_context(db, user),
            page=1,
            page_size=3,
        )
    else:
        all_book_ids = _shelf_book_ids(db, shelf, user, context=context)
        book_ids, total = all_book_ids[:3], len(all_book_ids)
    return {
        **_shelf_base_view(shelf),
        "bookCount": total,
        "books": _shelf_book_views(
            db,
            book_ids,
            context or authorization_context(db, user),
        ),
        "collectionIds": collection_ids
        if collection_ids is not None
        else shelf_store.list_collection_ids_by_shelf_ids(
            db,
            [str(shelf["id"])],
        ).get(str(shelf["id"]), []),
    }


def _shelf_member_view(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    collection_ids: list[str],
    context: AuthorizationContext | None = None,
) -> dict[str, Any]:
    summary = _shelf_summary_view(
        db,
        shelf,
        user,
        collection_ids=collection_ids,
        context=context,
    )
    return {
        key: summary[key]
        for key in (
            "id",
            "name",
            "description",
            "kind",
            "pinned",
            "bookCount",
            "books",
            "collectionIds",
            "createdAt",
            "updatedAt",
        )
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
    if str(shelf.get("kind") or "STATIC").upper() == ShelfKind.COLLECTION:
        return _collection_detail_view(
            db,
            shelf,
            user,
            page=page,
            page_size=page_size,
            include_member_shelf_ids=include_book_ids,
        )
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    context = authorization_context(db, user)
    kind = str(shelf.get("kind") or "STATIC").upper()
    if kind == "STATIC" and not include_book_ids:
        page_ids, total = shelf_store.list_static_shelf_book_page(
            db,
            str(shelf["id"]),
            context,
            page=page,
            page_size=page_size,
        )
        book_ids: list[str] = []
    else:
        book_ids = _shelf_book_ids(db, shelf, user, context=context)
        total = len(book_ids)
        start = (page - 1) * page_size
        page_ids = book_ids[start : start + page_size]
    total_pages = max(1, (total + page_size - 1) // page_size)
    result = {
        **_shelf_base_view(shelf),
        "bookCount": total,
        "books": _shelf_book_views(db, page_ids, context),
        "collectionIds": shelf_store.list_collection_ids_by_shelf_ids(
            db,
            [str(shelf["id"])],
        ).get(str(shelf["id"]), []),
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }
    if include_book_ids:
        result["bookIds"] = book_ids
    return result


def _collection_detail_view(
    db: Session,
    shelf: dict[str, Any],
    user: User,
    *,
    page: int,
    page_size: int,
    include_member_shelf_ids: bool,
) -> dict[str, Any]:
    member_shelf_ids = shelf_store.list_member_shelf_ids(db, str(shelf["id"]))
    members = shelf_store.list_owned_shelves_by_ids(
        db,
        member_shelf_ids,
        user.id,
    )
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = len(members)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    page_members = members[start : start + page_size]
    collection_ids_by_shelf_id = shelf_store.list_collection_ids_by_shelf_ids(
        db,
        [str(member["id"]) for member in page_members],
    )
    context = authorization_context(db, user)
    result = {
        **_shelf_base_view(shelf),
        "shelfCount": total,
        "shelves": [
            _shelf_member_view(
                db,
                member,
                user,
                collection_ids=collection_ids_by_shelf_id.get(
                    str(member["id"]),
                    [],
                ),
                context=context,
            )
            for member in page_members
        ],
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }
    if include_member_shelf_ids:
        result["memberShelfIds"] = member_shelf_ids
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
    if value.get("publishers"):
        return {}, "不支持的筛选维度：publisher"
    for key in ("tags", "authors"):
        values = [
            str(item).strip() for item in value.get(key) or [] if str(item).strip()
        ]
        if values:
            rules[key] = list(dict.fromkeys(values))[:100]
    dynamic_rules, dynamic_error = normalize_filter_rules(
        {
            "combinator": value.get("combinator", "ALL"),
            "conditions": value.get("conditions") or [],
        }
    )
    if dynamic_error:
        return {}, dynamic_error
    if dynamic_rules["conditions"]:
        rules.update(dynamic_rules)
    included_book_ids = [
        str(item).strip()
        for item in value.get("includedBookIds") or []
        if str(item).strip()
    ]
    if included_book_ids:
        rules["includedBookIds"] = list(dict.fromkeys(included_book_ids))[:500]
    return rules, None


def _normalized_shelf_book_ids(
    db: Session, value: Any, user: User
) -> tuple[list[str], str | None]:
    if not isinstance(value, list):
        return [], "图书列表格式不正确"
    book_ids: list[str] = []
    seen: set[str] = set()
    for item in value:
        book_id = str(item or "").strip()
        if book_id and book_id not in seen:
            seen.add(book_id)
            book_ids.append(book_id)
    if not book_ids:
        return [], None
    visible_ids = shelf_store.filter_visible_book_ids(
        db,
        book_ids,
        authorization_context(db, user),
    )
    if len(visible_ids) != len(book_ids):
        return [], "选择的图书不存在，请刷新后重试"
    return book_ids, None


def _normalized_ids(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        item_id = str(item or "").strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result


def _owned_shelves_for_membership(
    db: Session,
    *,
    shelf_ids: list[str],
    user_id: str,
) -> list[dict[str, Any]]:
    shelves = shelf_store.list_owned_shelves_by_ids(db, shelf_ids, user_id)
    if len(shelves) != len(shelf_ids):
        raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
    return shelves


def _validate_collection_member_shelves(
    db: Session,
    *,
    shelf_ids: list[str],
    owner_id: str,
) -> None:
    shelves = _owned_shelves_for_membership(
        db,
        shelf_ids=shelf_ids,
        user_id=owner_id,
    )
    validate_member_replacement(
        owner_id=owner_id,
        members=tuple(
            ShelfReference(
                id=str(shelf["id"]),
                kind=ShelfKind.parse(shelf.get("kind")),
                owner_id=(
                    str(shelf["ownerUserId"])
                    if shelf.get("ownerUserId") is not None
                    else None
                ),
            )
            for shelf in shelves
        ),
    )


def _validate_collection_ids(
    db: Session,
    *,
    collection_ids: list[str],
    owner_id: str,
) -> None:
    collections = _owned_shelves_for_membership(
        db,
        shelf_ids=collection_ids,
        user_id=owner_id,
    )
    validate_collection_replacement(
        owner_id=owner_id,
        collections=tuple(
            ShelfReference(
                id=str(collection["id"]),
                kind=ShelfKind.parse(collection.get("kind")),
                owner_id=(
                    str(collection["ownerUserId"])
                    if collection.get("ownerUserId") is not None
                    else None
                ),
            )
            for collection in collections
        ),
    )


def _collection_policy_response(
    error: ShelfCollectionPolicyError,
    *,
    status_code: int = 400,
) -> Response:
    messages = {
        "INVALID_SHELF_KIND": "书架类型无效",
        "INVALID_SHELF_KIND_TRANSITION": "合集类型创建后不能转换",
        "INVALID_COLLECTION_MEMBER": "合集只能包含当前用户的普通或智能书架",
        "COLLECTION_CANNOT_CONTAIN_BOOKS": "合集不能包含图书",
        "COLLECTION_CANNOT_HAVE_RULES": "合集不能设置智能书架规则",
        "SHELF_COLLECTION_NOT_EMPTY": "合集仍有书架，请先移除全部书架",
    }
    return fail(
        messages.get(error.code, "书架合集操作无效"),
        status_code=status_code,
        code=error.code,
    )


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
    return ok(
        {
            "shelf": _shelf_detail_view(
                db,
                shelf,
                user,
                page=page,
                page_size=pageSize,
                include_book_ids=includeBookIds,
            )
        }
    )


@router.post("/shelves", status_code=201)
def create_shelf(
    request_payload: ShelfWriteRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = _validated_shelf_payload(request_payload)
    name = str(payload.get("name") or "").strip()
    if not name:
        return fail("请填写书架名称", status_code=400)
    try:
        kind = ShelfKind.parse(payload.get("kind"))
    except ShelfCollectionPolicyError as error:
        return _collection_policy_response(error)
    rules, rules_error = _normalized_smart_shelf_rules(payload.get("rules"))
    if rules_error:
        return fail(
            rules_error,
            status_code=400,
            code=(
                "UNSUPPORTED_FILTER_DIMENSION"
                if rules_error.startswith("不支持的筛选维度：")
                else "INVALID_SHELF_RULES"
            ),
        )
    raw_book_ids = payload.get("bookIds", payload.get("bookIds", []))
    if kind is ShelfKind.COLLECTION:
        supplied_book_ids = _normalized_ids(raw_book_ids)
        try:
            validate_shelf_content(
                kind=kind,
                book_ids=tuple(supplied_book_ids or ()),
                has_smart_rules=bool(rules),
            )
        except ShelfCollectionPolicyError as error:
            return _collection_policy_response(error)
        book_ids: list[str] = []
    else:
        book_ids, book_error = _normalized_shelf_book_ids(
            db,
            raw_book_ids,
            user,
        )
        if book_error:
            return fail(book_error, status_code=400)
    member_shelf_ids = _normalized_ids(payload.get("memberShelfIds", []))
    collection_ids = _normalized_ids(payload.get("collectionIds", []))
    if member_shelf_ids is None or collection_ids is None:
        return _collection_policy_response(
            ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
        )
    try:
        if kind is ShelfKind.COLLECTION:
            if collection_ids:
                raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
            _validate_collection_member_shelves(
                db,
                shelf_ids=member_shelf_ids,
                owner_id=user.id,
            )
        else:
            if member_shelf_ids:
                raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
            _validate_collection_ids(
                db,
                collection_ids=collection_ids,
                owner_id=user.id,
            )
    except ShelfCollectionPolicyError as error:
        return _collection_policy_response(error)

    now = _now()
    shelf = CreateShelf(shelf_store, db).execute(
        CreateShelfCommand(
            values={
                "id": f"py_{time_ns()}",
                "ownerUserId": user.id,
                "name": name,
                "description": str(payload.get("description") or "").strip() or None,
                "kind": kind.value,
                "rulesJson": _json_text(rules),
                "pinned": bool(payload.get("pinned")),
                "createdAt": now,
                "updatedAt": now,
            },
            kind=kind,
            book_ids=tuple(book_ids),
            member_shelf_ids=tuple(member_shelf_ids),
            collection_ids=tuple(collection_ids),
            now=now,
        )
    )
    return ok({"shelf": _shelf_detail_view(db, shelf, user)}, status_code=201)


@router.patch("/shelves/{shelf_id}")
def update_shelf(
    shelf_id: str,
    request_payload: ShelfWriteRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    payload = _validated_shelf_payload(request_payload)
    values = {
        key: payload[key] for key in ("name", "description", "pinned") if key in payload
    }
    if "name" in values:
        values["name"] = str(values["name"] or "").strip()
        if not values["name"]:
            return fail("请填写书架名称", status_code=400)
    if "description" in values:
        values["description"] = str(values["description"] or "").strip() or None
    existing_shelf = _owned_shelf(db, shelf_id, user.id)
    if not existing_shelf:
        return fail("书架不存在", status_code=404)
    try:
        existing_kind = ShelfKind.parse(existing_shelf.get("kind"))
        kind = ShelfKind.parse(payload.get("kind", existing_kind.value))
        if (existing_kind is ShelfKind.COLLECTION) != (kind is ShelfKind.COLLECTION):
            raise ShelfCollectionPolicyError("INVALID_SHELF_KIND_TRANSITION")
    except ShelfCollectionPolicyError as error:
        return _collection_policy_response(error)
    rules, rules_error = _normalized_smart_shelf_rules(
        payload.get("rules", _parse_json(existing_shelf.get("rulesJson"), {}))
    )
    if rules_error:
        return fail(
            rules_error,
            status_code=400,
            code=(
                "UNSUPPORTED_FILTER_DIMENSION"
                if rules_error.startswith("不支持的筛选维度：")
                else "INVALID_SHELF_RULES"
            ),
        )
    values.update({"kind": kind.value, "rulesJson": _json_text(rules)})
    books = payload.get("bookIds", payload.get("bookIds"))
    book_ids: list[str] | None = None
    if books is not None:
        if kind is ShelfKind.COLLECTION:
            book_ids = _normalized_ids(books)
            if book_ids is None:
                return fail("图书列表格式不正确", status_code=400)
        else:
            book_ids, book_error = _normalized_shelf_book_ids(db, books, user)
            if book_error:
                return fail(book_error, status_code=400)
    try:
        validate_shelf_content(
            kind=kind,
            book_ids=tuple(book_ids or ()),
            has_smart_rules=bool(rules),
        )
    except ShelfCollectionPolicyError as error:
        return _collection_policy_response(error)
    member_shelf_ids = (
        _normalized_ids(payload["memberShelfIds"])
        if "memberShelfIds" in payload
        else None
    )
    collection_ids = (
        _normalized_ids(payload["collectionIds"])
        if "collectionIds" in payload
        else None
    )
    if member_shelf_ids is None and "memberShelfIds" in payload:
        return _collection_policy_response(
            ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
        )
    if collection_ids is None and "collectionIds" in payload:
        return _collection_policy_response(
            ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
        )
    try:
        if kind is ShelfKind.COLLECTION:
            if collection_ids:
                raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
            if member_shelf_ids is not None:
                _validate_collection_member_shelves(
                    db,
                    shelf_ids=member_shelf_ids,
                    owner_id=user.id,
                )
        else:
            if member_shelf_ids:
                raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
            if collection_ids is not None:
                _validate_collection_ids(
                    db,
                    collection_ids=collection_ids,
                    owner_id=user.id,
                )
    except ShelfCollectionPolicyError as error:
        return _collection_policy_response(error)
    updated_at = _now()
    values["updatedAt"] = updated_at
    previous_member_shelf_ids = (
        shelf_store.list_member_shelf_ids(db, shelf_id)
        if kind is ShelfKind.COLLECTION
        else []
    )
    previous_collection_ids = (
        shelf_store.list_collection_ids_by_shelf_ids(db, [shelf_id]).get(
            shelf_id,
            [],
        )
        if kind is not ShelfKind.COLLECTION
        else []
    )

    shelf = UpdateShelf(shelf_store, db).execute(
        UpdateShelfCommand(
            shelf_id=shelf_id,
            values=values,
            existing_kind=existing_kind,
            kind=kind,
            book_ids=tuple(book_ids) if book_ids is not None else None,
            member_shelf_ids=(
                tuple(member_shelf_ids) if member_shelf_ids is not None else None
            ),
            collection_ids=(
                tuple(collection_ids) if collection_ids is not None else None
            ),
            previous_member_shelf_ids=tuple(previous_member_shelf_ids),
            previous_collection_ids=tuple(previous_collection_ids),
            now=updated_at,
        )
    )
    if not shelf:
        return fail("书架不存在", status_code=404)
    return ok({"shelf": _shelf_detail_view(db, shelf, user)})


@router.delete("/shelves/{shelf_id}")
def delete_shelf(
    shelf_id: str,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DeletedShelfResponse:
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    shelf = _owned_shelf(db, shelf_id, user.id)
    if not shelf:
        return fail("书架不存在", status_code=404)
    if ShelfKind.parse(
        shelf.get("kind")
    ) is ShelfKind.COLLECTION and shelf_store.collection_has_members(db, shelf_id):
        return _collection_policy_response(
            ShelfCollectionPolicyError("SHELF_COLLECTION_NOT_EMPTY"),
            status_code=409,
        )

    try:
        deleted = DeleteShelf(shelf_store, db).execute(
            DeleteShelfCommand(
                shelf_id=shelf_id,
                is_collection=(
                    ShelfKind.parse(shelf.get("kind")) is ShelfKind.COLLECTION
                ),
                now=_now(),
            )
        )
    except ValueError as error:
        if str(error) != "SHELF_COLLECTION_NOT_EMPTY":
            raise
        return _collection_policy_response(
            ShelfCollectionPolicyError("SHELF_COLLECTION_NOT_EMPTY"),
            status_code=409,
        )
    return ok({"deleted": deleted, "id": shelf_id})
