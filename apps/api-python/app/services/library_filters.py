from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, authorization_context
from app.models.auth import User
from app.models.library import (
    LibraryFacet,
    LibraryVolume,
    LibraryWork,
)
from app.models.settings import MonitorFolder
from app.models.shelf import Shelf
from app.modules.library.application.filter_ast import (
    InvalidFilterExpression,
    parse_filter_expression,
)
from app.modules.library.infrastructure.filter_query import compile_filter_expression

TEXT_OPERATORS = [
    "contains",
    "not_contains",
    "equals",
    "not_equals",
    "starts_with",
    "ends_with",
    "is_empty",
    "is_not_empty",
]
SELECT_OPERATORS = ["equals", "not_equals", "is_empty", "is_not_empty"]
NUMBER_OPERATORS = [
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "between",
    "is_empty",
    "is_not_empty",
]
DATE_OPERATORS = [
    "equals",
    "not_equals",
    "after",
    "on_or_after",
    "before",
    "on_or_before",
    "between",
    "is_empty",
    "is_not_empty",
]
BOOLEAN_OPERATORS = ["is_true", "is_false"]


FILTER_FIELDS: list[dict[str, Any]] = [
    {
        "key": "title",
        "label": "书名",
        "group": "作品元数据",
        "type": "text",
        "operators": TEXT_OPERATORS,
    },
    {
        "key": "author",
        "label": "作者",
        "group": "作品元数据",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "authors",
        "allowCustom": True,
    },
    {
        "key": "tag",
        "label": "标签",
        "group": "作品元数据",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "tags",
        "allowCustom": True,
    },
    {
        "key": "series",
        "label": "丛书",
        "group": "作品元数据",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "series",
        "allowCustom": True,
    },
    {
        "key": "description",
        "label": "简介",
        "group": "作品元数据",
        "type": "text",
        "operators": TEXT_OPERATORS,
    },
    {
        "key": "seriesIndex",
        "label": "丛书序号",
        "group": "作品元数据",
        "type": "number",
        "operators": NUMBER_OPERATORS,
    },
    {
        "key": "metadataQuality",
        "label": "元数据完整度",
        "group": "作品元数据",
        "type": "number",
        "operators": NUMBER_OPERATORS,
        "unit": "%",
    },
    {
        "key": "volumeTitle",
        "label": "卷册名称",
        "group": "卷册元数据",
        "type": "text",
        "operators": TEXT_OPERATORS,
    },
    {
        "key": "narrator",
        "label": "演播者",
        "group": "卷册元数据",
        "type": "text",
        "operators": TEXT_OPERATORS,
    },
    {
        "key": "mediaKind",
        "label": "读物类型",
        "group": "格式与文件",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "mediaKinds",
    },
    {
        "key": "format",
        "label": "文件格式",
        "group": "格式与文件",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "formats",
        "allowCustom": True,
    },
    {
        "key": "fileSize",
        "label": "文件总大小",
        "group": "格式与文件",
        "type": "number",
        "operators": NUMBER_OPERATORS,
        "unit": "MB",
        "valueScale": 1048576,
    },
    {
        "key": "pageCount",
        "label": "页数",
        "group": "格式与文件",
        "type": "number",
        "operators": NUMBER_OPERATORS,
    },
    {
        "key": "chapterCount",
        "label": "章节数",
        "group": "格式与文件",
        "type": "number",
        "operators": NUMBER_OPERATORS,
    },
    {
        "key": "duration",
        "label": "时长",
        "group": "格式与文件",
        "type": "number",
        "operators": NUMBER_OPERATORS,
        "unit": "分钟",
        "valueScale": 60000,
    },
    {
        "key": "volumeCount",
        "label": "卷册数量",
        "group": "格式与文件",
        "type": "number",
        "operators": NUMBER_OPERATORS,
    },
    {
        "key": "sourcePath",
        "label": "原始文件路径",
        "group": "格式与文件",
        "type": "text",
        "operators": TEXT_OPERATORS,
    },
    {
        "key": "readingStatus",
        "label": "阅读状态",
        "group": "阅读与整理",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "readingStatuses",
    },
    {
        "key": "progress",
        "label": "阅读进度",
        "group": "阅读与整理",
        "type": "number",
        "operators": NUMBER_OPERATORS,
        "unit": "%",
    },
    {
        "key": "lastReadAt",
        "label": "最近阅读时间",
        "group": "阅读与整理",
        "type": "date",
        "operators": DATE_OPERATORS,
    },
    {
        "key": "publicationStatus",
        "label": "连载状态",
        "group": "阅读与整理",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "publicationStatuses",
    },
    {
        "key": "trackingStatus",
        "label": "追踪状态",
        "group": "阅读与整理",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "trackingStatuses",
    },
    {
        "key": "organizeStatus",
        "label": "整理状态",
        "group": "阅读与整理",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "organizeStatuses",
    },
    {
        "key": "organized",
        "label": "已完成整理",
        "group": "阅读与整理",
        "type": "boolean",
        "operators": BOOLEAN_OPERATORS,
    },
    {
        "key": "hasCover",
        "label": "有封面",
        "group": "阅读与整理",
        "type": "boolean",
        "operators": BOOLEAN_OPERATORS,
    },
    {
        "key": "shelf",
        "label": "所在普通书架",
        "group": "来源与归档",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "shelves",
    },
    {
        "key": "monitorFolder",
        "label": "原始文件夹",
        "group": "来源与归档",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "monitorFolders",
    },
    {
        "key": "origin",
        "label": "加入来源",
        "group": "来源与归档",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "origins",
        "allowCustom": True,
    },
    {
        "key": "importStatus",
        "label": "导入状态",
        "group": "来源与归档",
        "type": "select",
        "operators": SELECT_OPERATORS,
        "optionSource": "importStatuses",
        "allowCustom": True,
    },
    {
        "key": "createdAt",
        "label": "加入时间",
        "group": "来源与归档",
        "type": "date",
        "operators": DATE_OPERATORS,
    },
    {
        "key": "updatedAt",
        "label": "最后更新时间",
        "group": "来源与归档",
        "type": "date",
        "operators": DATE_OPERATORS,
    },
]

FIELD_BY_KEY = {str(field["key"]): field for field in FILTER_FIELDS}

STATIC_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "readingStatuses": [
        ("UNREAD", "未开始"),
        ("READING", "进行中"),
        ("FINISHED", "已完成"),
    ],
    "publicationStatuses": [
        ("UNKNOWN", "未知"),
        ("ONGOING", "连载中"),
        ("COMPLETED", "已完结"),
        ("HIATUS", "暂停"),
        ("CANCELLED", "已取消"),
    ],
    "trackingStatuses": [
        ("NOT_TRACKING", "未追踪"),
        ("TRACKING", "追踪中"),
        ("PAUSED", "已暂停"),
        ("IGNORED", "已忽略"),
    ],
    "organizeStatuses": [
        ("PENDING", "待整理"),
        ("REVIEWING", "待确认"),
        ("APPLIED", "已应用"),
        ("FAILED", "失败"),
    ],
    "mediaKinds": [("EBOOK", "电子书"), ("COMIC", "漫画"), ("AUDIOBOOK", "有声书")],
}


def _table_exists(db: Session, table: str) -> bool:
    try:
        return sa_inspect(db.connection()).has_table(table)
    except Exception:
        return False


def _option(
    value: Any, label: Any = None, count: Any = None, **extra: Any
) -> dict[str, Any]:
    item = {"value": str(value), "label": str(label if label is not None else value)}
    if count is not None:
        item["count"] = int(count or 0)
    item.update(extra)
    return item


def _distinct_volume_options(
    db: Session,
    column: Any,
) -> list[dict[str, Any]]:
    if not _table_exists(db, LibraryVolume.__tablename__):
        return []
    normalized = func.trim(func.coalesce(column, ""))
    rows = db.execute(
        select(normalized.label("value"), func.count().label("count"))
        .where(
            LibraryVolume.hidden.is_(False),
            normalized != "",
        )
        .group_by(normalized)
        .order_by(func.count().desc(), normalized.asc())
    ).all()
    return [_option(row.value, count=row.count) for row in rows]


def _distinct_work_options(
    db: Session,
    column: Any,
) -> list[dict[str, Any]]:
    if not _table_exists(db, LibraryWork.__tablename__):
        return []
    normalized = func.trim(func.coalesce(column, ""))
    rows = db.execute(
        select(normalized.label("value"), func.count().label("count"))
        .where(
            func.coalesce(LibraryWork.hidden, False).is_(False),
            normalized != "",
        )
        .group_by(normalized)
        .order_by(func.count().desc(), normalized.asc())
    ).all()
    return [_option(row.value, count=row.count) for row in rows]


def library_filter_schema(db: Session) -> dict[str, Any]:
    options: dict[str, list[dict[str, Any]]] = {
        key: [_option(value, label) for value, label in values]
        for key, values in STATIC_OPTIONS.items()
    }
    if _table_exists(db, LibraryFacet.__tablename__):
        facet_sources = {
            "AUTHOR": "authors",
            "TAG": "tags",
            "SERIES": "series",
        }
        for source in facet_sources.values():
            options[source] = []
        facet_rows = db.execute(
            select(LibraryFacet.kind, LibraryFacet.name).order_by(
                LibraryFacet.name.asc()
            )
        ).all()
        for row in facet_rows:
            source = facet_sources.get(str(row.kind or "").upper())
            if source:
                options[source].append(_option(row.name))
    options["formats"] = _distinct_volume_options(db, LibraryVolume.format)
    options["importStatuses"] = _distinct_volume_options(
        db, LibraryVolume.import_status
    )
    work_origins = _distinct_work_options(db, LibraryWork.origin)
    volume_origins = _distinct_volume_options(db, LibraryVolume.origin)
    origin_values = {item["value"]: item for item in [*work_origins, *volume_origins]}
    options["origins"] = sorted(origin_values.values(), key=lambda item: item["label"])
    options["monitorFolders"] = (
        [
            _option(row.id, row.name, rootPath=row.root_path)
            for row in db.execute(
                select(
                    MonitorFolder.id,
                    MonitorFolder.name,
                    MonitorFolder.root_path,
                ).order_by(MonitorFolder.name.asc())
            ).all()
        ]
        if _table_exists(db, MonitorFolder.__tablename__)
        else []
    )
    options["shelves"] = (
        [
            _option(row.id, row.name)
            for row in db.execute(
                select(Shelf.id, Shelf.name)
                .where(func.coalesce(Shelf.kind, "STATIC") == "STATIC")
                .order_by(Shelf.name.asc())
            ).all()
        ]
        if _table_exists(db, Shelf.__tablename__)
        else []
    )
    fields = [
        {**field, "options": options.get(str(field.get("optionSource")), [])}
        for field in FILTER_FIELDS
    ]
    return {"fields": fields, "maxConditions": 30}


def normalize_filter_rules(value: Any) -> tuple[dict[str, Any], str | None]:
    if value in (None, ""):
        return {"combinator": "ALL", "conditions": []}, None
    if not isinstance(value, dict):
        return {}, "筛选规则格式不正确"
    combinator = str(value.get("combinator") or "ALL").upper()
    if combinator not in {"ALL", "ANY"}:
        return {}, "筛选条件组合方式无效"
    raw_conditions = value.get("conditions") or []
    if not isinstance(raw_conditions, list):
        return {}, "筛选条件格式不正确"
    if len(raw_conditions) > 30:
        return {}, "筛选条件最多支持 30 条"
    conditions: list[dict[str, Any]] = []
    for raw in raw_conditions:
        if not isinstance(raw, dict):
            return {}, "筛选条件格式不正确"
        field_key = str(raw.get("field") or "").strip()
        field = FIELD_BY_KEY.get(field_key)
        if not field:
            return {}, f"不支持的筛选维度：{field_key or '空'}"
        operator = str(raw.get("operator") or "").strip()
        if operator not in field["operators"]:
            return {}, f"{field['label']}不支持这个条件"
        normalized: dict[str, Any] = {"field": field_key, "operator": operator}
        if operator not in {"is_empty", "is_not_empty", "is_true", "is_false"}:
            raw_value = raw.get("value")
            if operator == "between":
                if (
                    not isinstance(raw_value, list)
                    or len(raw_value) != 2
                    or any(str(item).strip() == "" for item in raw_value)
                ):
                    return {}, f"请填写{field['label']}的完整范围"
                normalized["value"] = [
                    str(raw_value[0]).strip(),
                    str(raw_value[1]).strip(),
                ]
            else:
                next_value = str(raw_value if raw_value is not None else "").strip()
                if not next_value:
                    return {}, f"请填写{field['label']}的筛选值"
                normalized["value"] = next_value[:500]
        conditions.append(normalized)
    return {"combinator": combinator, "conditions": conditions}, None


def _authorization_context_for_user(
    db: Session,
    user_id: str | None,
) -> AuthorizationContext:
    user = db.get(User, user_id) if user_id else None
    if user is not None:
        return authorization_context(db, user)
    return AuthorizationContext(
        user_id=user_id or "",
        is_admin=True,
        can_manage_system=True,
        can_view_manual_imports=True,
        monitor_folder_ids=(),
        authz_version=1,
    )


def compile_filter_predicate(
    db: Session,
    rules: dict[str, Any],
    *,
    user_id: str | None = None,
    shelf_owner_user_id: str | None = None,
) -> tuple[ColumnElement[bool] | None, str | None]:
    normalized, error = normalize_filter_rules(rules)
    if error:
        return None, error
    try:
        expression = parse_filter_expression(normalized)
    except InvalidFilterExpression as exc:
        return None, str(exc)
    context = _authorization_context_for_user(db, user_id)
    try:
        return (
            compile_filter_expression(
                expression,
                context=context,
                user_id=user_id,
                shelf_owner_user_id=shelf_owner_user_id,
            ),
            None,
        )
    except ValueError as exc:
        return None, str(exc)


def compile_filter_rules(
    db: Session,
    rules: dict[str, Any],
    *,
    alias: str = "w",
    user_id: str | None = None,
    param_prefix: str = "smart_filter",
    shelf_owner_user_id: str | None = None,
) -> tuple[ColumnElement[bool] | None, dict[str, Any], str | None]:
    del alias, param_prefix
    predicate, error = compile_filter_predicate(
        db,
        rules,
        user_id=user_id,
        shelf_owner_user_id=shelf_owner_user_id,
    )
    return predicate, {}, error
