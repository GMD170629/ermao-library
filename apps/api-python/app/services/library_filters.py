from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.time import to_timestamp_ms


TEXT_OPERATORS = ["contains", "not_contains", "equals", "not_equals", "starts_with", "ends_with", "is_empty", "is_not_empty"]
SELECT_OPERATORS = ["equals", "not_equals", "is_empty", "is_not_empty"]
NUMBER_OPERATORS = ["equals", "not_equals", "greater_than", "greater_or_equal", "less_than", "less_or_equal", "between", "is_empty", "is_not_empty"]
DATE_OPERATORS = ["equals", "not_equals", "after", "on_or_after", "before", "on_or_before", "between", "is_empty", "is_not_empty"]
BOOLEAN_OPERATORS = ["is_true", "is_false"]


FILTER_FIELDS: list[dict[str, Any]] = [
    {"key": "title", "label": "书名", "group": "作品元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "author", "label": "作者", "group": "作品元数据", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "authors", "allowCustom": True},
    {"key": "tag", "label": "标签", "group": "作品元数据", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "tags", "allowCustom": True},
    {"key": "series", "label": "丛书", "group": "作品元数据", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "series", "allowCustom": True},
    {"key": "description", "label": "简介", "group": "作品元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "publishedYear", "label": "出版年份", "group": "作品元数据", "type": "number", "operators": NUMBER_OPERATORS},
    {"key": "seriesIndex", "label": "丛书序号", "group": "作品元数据", "type": "number", "operators": NUMBER_OPERATORS},
    {"key": "metadataQuality", "label": "元数据完整度", "group": "作品元数据", "type": "number", "operators": NUMBER_OPERATORS, "unit": "%"},
    {"key": "publisher", "label": "出版社", "group": "版本元数据", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "publishers", "allowCustom": True},
    {"key": "language", "label": "语言", "group": "版本元数据", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "languages", "allowCustom": True},
    {"key": "isbn", "label": "ISBN", "group": "版本元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "identifier", "label": "外部标识", "group": "版本元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "editionName", "label": "版本名称", "group": "版本元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "narrator", "label": "演播者", "group": "版本元数据", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "mediaKind", "label": "读物类型", "group": "格式与文件", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "mediaKinds"},
    {"key": "format", "label": "文件格式", "group": "格式与文件", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "formats", "allowCustom": True},
    {"key": "fileSize", "label": "文件总大小", "group": "格式与文件", "type": "number", "operators": NUMBER_OPERATORS, "unit": "MB", "valueScale": 1048576},
    {"key": "pageCount", "label": "页数", "group": "格式与文件", "type": "number", "operators": NUMBER_OPERATORS},
    {"key": "chapterCount", "label": "章节数", "group": "格式与文件", "type": "number", "operators": NUMBER_OPERATORS},
    {"key": "duration", "label": "时长", "group": "格式与文件", "type": "number", "operators": NUMBER_OPERATORS, "unit": "分钟", "valueScale": 60000},
    {"key": "versionCount", "label": "版本数量", "group": "格式与文件", "type": "number", "operators": NUMBER_OPERATORS},
    {"key": "sourcePath", "label": "原始文件路径", "group": "格式与文件", "type": "text", "operators": TEXT_OPERATORS},
    {"key": "readingStatus", "label": "阅读状态", "group": "阅读与整理", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "readingStatuses"},
    {"key": "progress", "label": "阅读进度", "group": "阅读与整理", "type": "number", "operators": NUMBER_OPERATORS, "unit": "%"},
    {"key": "lastReadAt", "label": "最近阅读时间", "group": "阅读与整理", "type": "date", "operators": DATE_OPERATORS},
    {"key": "publicationStatus", "label": "连载状态", "group": "阅读与整理", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "publicationStatuses"},
    {"key": "trackingStatus", "label": "追踪状态", "group": "阅读与整理", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "trackingStatuses"},
    {"key": "organizeStatus", "label": "整理状态", "group": "阅读与整理", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "organizeStatuses"},
    {"key": "organized", "label": "已完成整理", "group": "阅读与整理", "type": "boolean", "operators": BOOLEAN_OPERATORS},
    {"key": "hasCover", "label": "有封面", "group": "阅读与整理", "type": "boolean", "operators": BOOLEAN_OPERATORS},
    {"key": "shelf", "label": "所在普通书架", "group": "来源与归档", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "shelves"},
    {"key": "monitorFolder", "label": "原始文件夹", "group": "来源与归档", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "monitorFolders"},
    {"key": "origin", "label": "加入来源", "group": "来源与归档", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "origins", "allowCustom": True},
    {"key": "importStatus", "label": "导入状态", "group": "来源与归档", "type": "select", "operators": SELECT_OPERATORS, "optionSource": "importStatuses", "allowCustom": True},
    {"key": "createdAt", "label": "加入时间", "group": "来源与归档", "type": "date", "operators": DATE_OPERATORS},
    {"key": "updatedAt", "label": "最后更新时间", "group": "来源与归档", "type": "date", "operators": DATE_OPERATORS},
]

FIELD_BY_KEY = {str(field["key"]): field for field in FILTER_FIELDS}

STATIC_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "readingStatuses": [("UNREAD", "未开始"), ("READING", "进行中"), ("FINISHED", "已完成")],
    "publicationStatuses": [("UNKNOWN", "未知"), ("ONGOING", "连载中"), ("COMPLETED", "已完结"), ("HIATUS", "暂停"), ("CANCELLED", "已取消")],
    "trackingStatuses": [("NOT_TRACKING", "未追踪"), ("TRACKING", "追踪中"), ("PAUSED", "已暂停"), ("IGNORED", "已忽略")],
    "organizeStatuses": [("PENDING", "待整理"), ("REVIEWING", "待确认"), ("APPLIED", "已应用"), ("FAILED", "失败")],
    "mediaKinds": [("EBOOK", "电子书"), ("COMIC", "漫画"), ("AUDIOBOOK", "有声书")],
}


def _table_exists(db: Session, table: str) -> bool:
    return db.execute(text("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = :table"), {"table": table}).scalar() is not None


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text(sql), params or {}).mappings().all()]


def _option(value: Any, label: Any = None, count: Any = None, **extra: Any) -> dict[str, Any]:
    item = {"value": str(value), "label": str(label if label is not None else value)}
    if count is not None:
        item["count"] = int(count or 0)
    item.update(extra)
    return item


def _distinct_options(db: Session, table: str, column: str, *, where: str = "1 = 1") -> list[dict[str, Any]]:
    if not _table_exists(db, table):
        return []
    return [
        _option(row["value"], count=row["count"])
        for row in _rows(
            db,
            f"SELECT TRIM(`{column}`) AS `value`, COUNT(*) AS `count` FROM `{table}` "
            f"WHERE {where} AND TRIM(COALESCE(`{column}`, '')) != '' GROUP BY TRIM(`{column}`) ORDER BY COUNT(*) DESC, TRIM(`{column}`) ASC",
        )
    ]


def library_filter_schema(db: Session) -> dict[str, Any]:
    options: dict[str, list[dict[str, Any]]] = {
        key: [_option(value, label) for value, label in values]
        for key, values in STATIC_OPTIONS.items()
    }
    if _table_exists(db, "LibraryFacet"):
        facet_rows = _rows(
            db,
            "SELECT `kind`, `name`, COUNT(*) OVER (PARTITION BY `kind`) AS `kindCount` FROM `LibraryFacet` ORDER BY `name` COLLATE NOCASE ASC",
        )
        facet_sources = {"AUTHOR": "authors", "TAG": "tags", "SERIES": "series", "PUBLISHER": "publishers"}
        for source in facet_sources.values():
            options[source] = []
        for row in facet_rows:
            source = facet_sources.get(str(row.get("kind") or "").upper())
            if source:
                options[source].append(_option(row["name"]))
    options["languages"] = _distinct_options(db, "LibraryEdition", "language", where="COALESCE(`hidden`, 0) = 0")
    options["formats"] = _distinct_options(db, "LibraryEdition", "format", where="COALESCE(`hidden`, 0) = 0")
    options["importStatuses"] = _distinct_options(db, "LibraryEdition", "importStatus", where="COALESCE(`hidden`, 0) = 0")
    work_origins = _distinct_options(db, "LibraryWork", "origin", where="COALESCE(`hidden`, 0) = 0")
    edition_origins = _distinct_options(db, "LibraryEdition", "origin", where="COALESCE(`hidden`, 0) = 0")
    origin_values = {item["value"]: item for item in [*work_origins, *edition_origins]}
    options["origins"] = sorted(origin_values.values(), key=lambda item: item["label"])
    options["monitorFolders"] = (
        [_option(row["id"], row["name"], rootPath=row.get("rootPath")) for row in _rows(db, "SELECT `id`, `name`, `rootPath` FROM `MonitorFolder` ORDER BY `name` COLLATE NOCASE ASC")]
        if _table_exists(db, "MonitorFolder")
        else []
    )
    options["shelves"] = (
        [_option(row["id"], row["name"]) for row in _rows(db, "SELECT `id`, `name` FROM `Shelf` WHERE COALESCE(`kind`, 'STATIC') = 'STATIC' ORDER BY `name` COLLATE NOCASE ASC")]
        if _table_exists(db, "Shelf")
        else []
    )
    fields = [{**field, "options": options.get(str(field.get("optionSource")), [])} for field in FILTER_FIELDS]
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
                if not isinstance(raw_value, list) or len(raw_value) != 2 or any(str(item).strip() == "" for item in raw_value):
                    return {}, f"请填写{field['label']}的完整范围"
                normalized["value"] = [str(raw_value[0]).strip(), str(raw_value[1]).strip()]
            else:
                next_value = str(raw_value if raw_value is not None else "").strip()
                if not next_value:
                    return {}, f"请填写{field['label']}的筛选值"
                normalized["value"] = next_value[:500]
        conditions.append(normalized)
    return {"combinator": combinator, "conditions": conditions}, None


def _column(alias: str, name: str) -> str:
    return f"`{alias}`.`{name}`"


def _projected_reading_status_clause(
    alias: str,
    status: str,
    user_param: str,
    edition_scope_sql: str = "1 = 1",
) -> str:
    media_expression = "edition_state.`mediaKind`"
    visible_state_exists = (
        "EXISTS (SELECT 1 FROM `LibraryConsumptionState` consumption_state "
        f"WHERE consumption_state.`userId` = :{user_param} AND consumption_state.`workId` = `{alias}`.`id` "
        "AND EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        f"WHERE edition_state.`workId` = `{alias}`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope_sql} AND {media_expression} = consumption_state.`mediaKind`))"
    )
    any_visible_edition = (
        "EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        f"WHERE edition_state.`workId` = `{alias}`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope_sql})"
    )
    all_finished = (
        f"({any_visible_edition} AND NOT EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        f"WHERE edition_state.`workId` = `{alias}`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope_sql} AND NOT EXISTS (SELECT 1 FROM `LibraryConsumptionState` finished_state "
        f"WHERE finished_state.`userId` = :{user_param} AND finished_state.`workId` = `{alias}`.`id` "
        f"AND finished_state.`mediaKind` = {media_expression} AND finished_state.`status` = 'FINISHED')))"
    )
    has_started = (
        "EXISTS (SELECT 1 FROM `LibraryConsumptionState` started_state "
        f"WHERE started_state.`userId` = :{user_param} AND started_state.`workId` = `{alias}`.`id` "
        "AND started_state.`status` IN ('READING', 'FINISHED') "
        "AND EXISTS (SELECT 1 FROM `LibraryEdition` edition_state "
        f"WHERE edition_state.`workId` = `{alias}`.`id` AND COALESCE(edition_state.`hidden`, 0) = 0 "
        f"AND {edition_scope_sql} AND {media_expression} = started_state.`mediaKind`))"
    )
    if status == "FINISHED":
        return f"({visible_state_exists} AND {all_finished})"
    if status == "READING":
        return f"({visible_state_exists} AND NOT {all_finished} AND {has_started})"
    return f"(NOT {has_started})"


def _text_predicate(expression: str, operator: str, value: Any, key: str, params: dict[str, Any]) -> str:
    normalized = f"LOWER(TRIM(COALESCE({expression}, '')))"
    if operator == "is_empty":
        return f"{normalized} = ''"
    if operator == "is_not_empty":
        return f"{normalized} != ''"
    text_value = str(value or "").strip().lower()
    if operator in {"contains", "not_contains"}:
        params[key] = f"%{text_value}%"
        clause = f"{normalized} LIKE :{key}"
        return f"NOT ({clause})" if operator == "not_contains" else clause
    if operator == "starts_with":
        params[key] = f"{text_value}%"
        return f"{normalized} LIKE :{key}"
    if operator == "ends_with":
        params[key] = f"%{text_value}"
        return f"{normalized} LIKE :{key}"
    params[key] = text_value
    clause = f"{normalized} = :{key}"
    return f"NOT ({clause})" if operator == "not_equals" else clause


def _number_predicate(expression: str, operator: str, value: Any, key: str, params: dict[str, Any], scale: float = 1) -> str:
    if operator == "is_empty":
        return f"({expression}) IS NULL"
    if operator == "is_not_empty":
        return f"({expression}) IS NOT NULL"
    comparison = {"equals": "=", "not_equals": "!=", "greater_than": ">", "greater_or_equal": ">=", "less_than": "<", "less_or_equal": "<="}
    if operator == "between":
        first, second = value
        params[f"{key}_from"] = float(first) * scale
        params[f"{key}_to"] = float(second) * scale
        return f"CAST(({expression}) AS REAL) BETWEEN :{key}_from AND :{key}_to"
    params[key] = float(value) * scale
    return f"CAST(({expression}) AS REAL) {comparison[operator]} :{key}"


def _date_predicate(expression: str, operator: str, value: Any, key: str, params: dict[str, Any]) -> str:
    if operator == "is_empty":
        return f"({expression}) IS NULL"
    if operator == "is_not_empty":
        return f"({expression}) IS NOT NULL"
    def bounds(raw: Any) -> tuple[int, int]:
        parsed = date.fromisoformat(str(raw))
        start = to_timestamp_ms(f"{parsed.isoformat()}T00:00:00")
        end_date = parsed + timedelta(days=1)
        end = to_timestamp_ms(f"{end_date.isoformat()}T00:00:00")
        assert start is not None and end is not None
        return start, end

    raw_expression = f"({expression})"
    text_expression = f"CAST({raw_expression} AS TEXT)"
    cast_expression = (
        f"CASE WHEN {text_expression} GLOB '*[^0-9]*' "
        f"THEN CAST(ROUND((julianday({raw_expression}) - 2440587.5) * 86400000) AS INTEGER) "
        f"ELSE CAST({raw_expression} AS INTEGER) END"
    )
    if operator == "between":
        first, second = value
        start, _ = bounds(first)
        _, end = bounds(second)
        params[f"{key}_from"] = start
        params[f"{key}_to"] = end
        return f"({cast_expression} >= :{key}_from AND {cast_expression} < :{key}_to)"
    start, end = bounds(value)
    params[f"{key}_start"] = start
    params[f"{key}_end"] = end
    if operator == "equals":
        return f"({cast_expression} >= :{key}_start AND {cast_expression} < :{key}_end)"
    if operator == "not_equals":
        return f"NOT ({cast_expression} >= :{key}_start AND {cast_expression} < :{key}_end)"
    if operator == "after":
        return f"{cast_expression} >= :{key}_end"
    if operator == "on_or_after":
        return f"{cast_expression} >= :{key}_start"
    if operator == "before":
        return f"{cast_expression} < :{key}_start"
    return f"{cast_expression} < :{key}_end"


def _relation_text_clause(base_sql: str, expression: str, operator: str, value: Any, key: str, params: dict[str, Any]) -> str:
    if operator in {"not_contains", "not_equals", "is_empty"}:
        positive = {"not_contains": "contains", "not_equals": "equals", "is_empty": "is_not_empty"}[operator]
        predicate = _text_predicate(expression, positive, value, key, params)
        return f"NOT EXISTS ({base_sql} AND {predicate})"
    predicate = _text_predicate(expression, operator, value, key, params)
    return f"EXISTS ({base_sql} AND {predicate})"


def compile_filter_rules(
    db: Session,
    rules: dict[str, Any],
    *,
    alias: str = "w",
    user_id: str | None = None,
    param_prefix: str = "smart_filter",
    edition_scope_sql: str = "1 = 1",
    edition_scope_params: dict[str, Any] | None = None,
    shelf_owner_user_id: str | None = None,
) -> tuple[str | None, dict[str, Any], str | None]:
    normalized, error = normalize_filter_rules(rules)
    if error:
        return None, {}, error
    clauses: list[str] = []
    params: dict[str, Any] = dict(edition_scope_params or {})
    if shelf_owner_user_id:
        params[f"{param_prefix}_shelf_owner"] = shelf_owner_user_id
    work_columns = {
        "title": "title", "author": "author", "description": "description", "series": "seriesName",
        "publishedYear": "publishedYear", "seriesIndex": "seriesIndex", "metadataQuality": "metadataQuality",
        "readingStatus": "status", "publicationStatus": "publicationStatus", "trackingStatus": "trackingStatus",
        "organizeStatus": "organizeStatus", "origin": "origin", "createdAt": "createdAt", "updatedAt": "updatedAt",
    }
    edition_columns = {
        "publisher": "publisher", "language": "language", "isbn": "isbn", "identifier": "identifier",
        "editionName": "versionName", "narrator": "narrator", "mediaKind": "mediaKind", "format": "format",
        "importStatus": "importStatus",
    }
    for index, condition in enumerate(normalized["conditions"]):
        field_key = condition["field"]
        operator = condition["operator"]
        value = condition.get("value")
        key = f"{param_prefix}_{index}"
        spec = FIELD_BY_KEY[field_key]
        try:
            if field_key == "readingStatus" and user_id and _table_exists(db, "LibraryConsumptionState") and _table_exists(db, "LibraryEdition"):
                if operator == "is_empty":
                    clauses.append("0 = 1")
                elif operator == "is_not_empty":
                    clauses.append("1 = 1")
                else:
                    normalized_status = str(value or "UNREAD").upper()
                    params["filter_user_id"] = user_id
                    status_clause = _projected_reading_status_clause(
                        alias,
                        normalized_status,
                        "filter_user_id",
                        edition_scope_sql.replace("filter_edition", "edition_state"),
                    )
                    clauses.append(f"NOT ({status_clause})" if operator == "not_equals" else status_clause)
                continue
            if field_key in work_columns:
                expression = _column(alias, work_columns[field_key])
                if field_key == "readingStatus":
                    expression = f"CASE WHEN {expression} = 'WANT' THEN 'UNREAD' ELSE {expression} END"
                if spec["type"] in {"text", "select"}:
                    clauses.append(_text_predicate(expression, operator, value, key, params))
                elif spec["type"] == "number":
                    clauses.append(_number_predicate(expression, operator, value, key, params, float(spec.get("valueScale") or 1)))
                else:
                    clauses.append(_date_predicate(expression, operator, value, key, params))
                continue
            if field_key in edition_columns:
                if not _table_exists(db, "LibraryEdition"):
                    clauses.append("0 = 1")
                    continue
                base = f"SELECT 1 FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql}"
                clauses.append(_relation_text_clause(base, f"filter_edition.`{edition_columns[field_key]}`", operator, value, key, params))
                continue
            if field_key == "tag":
                if _table_exists(db, "LibraryWorkFacet") and _table_exists(db, "LibraryFacet"):
                    base = f"SELECT 1 FROM `LibraryWorkFacet` filter_link JOIN `LibraryFacet` filter_facet ON filter_facet.`id` = filter_link.`facetId` WHERE filter_link.`workId` = `{alias}`.`id` AND filter_facet.`kind` = 'TAG'"
                    clauses.append(_relation_text_clause(base, "filter_facet.`name`", operator, value, key, params))
                else:
                    clauses.append(_text_predicate(_column(alias, "tags"), operator, value, key, params))
                continue
            if field_key == "shelf":
                owner_clause = (
                    f" AND filter_shelf.`ownerUserId` = :{param_prefix}_shelf_owner"
                    if shelf_owner_user_id
                    else ""
                )
                base = f"SELECT 1 FROM `ShelfWork` filter_shelf_work JOIN `Shelf` filter_shelf ON filter_shelf.`id` = filter_shelf_work.`shelfId` WHERE filter_shelf_work.`workId` = `{alias}`.`id` AND COALESCE(filter_shelf.`kind`, 'STATIC') = 'STATIC'{owner_clause}"
                clauses.append(_relation_text_clause(base, "filter_shelf.`id`", operator, value, key, params))
                continue
            if field_key == "monitorFolder":
                params[key] = str(value or "")
                positive = f"({_column(alias, 'monitorFolderId')} = :{key} OR EXISTS (SELECT 1 FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND filter_edition.`monitorFolderId` = :{key} AND {edition_scope_sql}))"
                if operator == "is_empty":
                    clauses.append(f"({_column(alias, 'monitorFolderId')} IS NULL AND NOT EXISTS (SELECT 1 FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND filter_edition.`monitorFolderId` IS NOT NULL AND {edition_scope_sql}))")
                elif operator == "is_not_empty":
                    clauses.append(f"({_column(alias, 'monitorFolderId')} IS NOT NULL OR EXISTS (SELECT 1 FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND filter_edition.`monitorFolderId` IS NOT NULL AND {edition_scope_sql}))")
                else:
                    clauses.append(f"NOT ({positive})" if operator == "not_equals" else positive)
                continue
            if field_key == "sourcePath":
                base = f"SELECT 1 FROM `LibraryEdition` filter_edition JOIN `LibraryFile` filter_file ON filter_file.`editionId` = filter_edition.`id` WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql}"
                clauses.append(_relation_text_clause(base, "filter_file.`path`", operator, value, key, params))
                continue
            scalar_expressions = {
                "progress": f"(SELECT filter_progress.`percent` FROM `LibraryReadingProgress` filter_progress WHERE filter_progress.`workId` = `{alias}`.`id`" + (" AND filter_progress.`userId` = :filter_user_id" if user_id else "") + " ORDER BY filter_progress.`updatedAt` DESC, filter_progress.`id` DESC LIMIT 1)",
                "lastReadAt": f"(SELECT MAX(filter_progress.`updatedAt`) FROM `LibraryReadingProgress` filter_progress WHERE filter_progress.`workId` = `{alias}`.`id`" + (" AND filter_progress.`userId` = :filter_user_id" if user_id else "") + ")",
                "fileSize": f"(SELECT SUM(filter_file.`sizeBytes`) FROM `LibraryEdition` filter_edition JOIN `LibraryFile` filter_file ON filter_file.`editionId` = filter_edition.`id` WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql})",
                "pageCount": f"(SELECT MAX(filter_edition.`pageCount`) FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql})",
                "chapterCount": f"(SELECT MAX(filter_edition.`chapterCount`) FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql})",
                "duration": f"(SELECT MAX(filter_edition.`durationMs`) FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql})",
                "versionCount": f"(SELECT COUNT(*) FROM `LibraryEdition` filter_edition WHERE filter_edition.`workId` = `{alias}`.`id` AND COALESCE(filter_edition.`hidden`, 0) = 0 AND {edition_scope_sql})",
            }
            if field_key in scalar_expressions:
                expression = scalar_expressions[field_key]
                if user_id and field_key in {"progress", "lastReadAt"}:
                    params["filter_user_id"] = user_id
                if spec["type"] == "date":
                    clauses.append(_date_predicate(expression, operator, value, key, params))
                else:
                    clauses.append(_number_predicate(expression, operator, value, key, params, float(spec.get("valueScale") or 1)))
                continue
            if field_key == "organized":
                expression = f"COALESCE({_column(alias, 'organized')}, 0) = 1"
                clauses.append(expression if operator == "is_true" else f"NOT ({expression})")
                continue
            if field_key == "hasCover":
                expression = f"(TRIM(COALESCE({_column(alias, 'coverPath')}, '')) != '' AND COALESCE({_column(alias, 'coverStatus')}, '') = 'READY')"
                clauses.append(expression if operator == "is_true" else f"NOT ({expression})")
                continue
        except (TypeError, ValueError):
            return None, {}, f"{spec['label']}的筛选值无效"
    if not clauses:
        return None, params, None
    joiner = " AND " if normalized["combinator"] == "ALL" else " OR "
    return f"({joiner.join(clauses)})", params, None
