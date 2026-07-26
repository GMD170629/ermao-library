from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from appv2.modules.reporting.contracts import LibraryFilterCondition

SqlParams = dict[str, object]

TEXT_OPERATORS = (
    "contains",
    "not_contains",
    "equals",
    "not_equals",
    "starts_with",
    "ends_with",
    "is_empty",
    "is_not_empty",
)
SELECT_OPERATORS = ("equals", "not_equals", "is_empty", "is_not_empty")
NUMBER_OPERATORS = (
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "between",
    "is_empty",
    "is_not_empty",
)
DATE_OPERATORS = (
    "equals",
    "not_equals",
    "after",
    "on_or_after",
    "before",
    "on_or_before",
    "between",
    "is_empty",
    "is_not_empty",
)


def reading_status_clause(status: str) -> str:
    started = (
        "EXISTS (SELECT 1 FROM reading.progress AS started_progress "
        "JOIN catalog.editions AS started_edition "
        "ON started_edition.id = started_progress.edition_id "
        "WHERE started_progress.user_id = :account_id "
        "AND started_edition.work_id = w.id "
        "AND started_progress.percentage > 0)"
    )
    has_editions = "EXISTS (SELECT 1 FROM catalog.editions WHERE work_id = w.id)"
    unfinished = (
        "EXISTS (SELECT 1 FROM catalog.editions AS unfinished_edition "
        "WHERE unfinished_edition.work_id = w.id "
        "AND NOT EXISTS (SELECT 1 FROM reading.progress AS finished_progress "
        "WHERE finished_progress.user_id = :account_id "
        "AND finished_progress.edition_id = unfinished_edition.id "
        "AND finished_progress.percentage >= 0.999))"
    )
    finished = f"({has_editions} AND NOT {unfinished})"
    if status == "UNREAD":
        return f"NOT {started}"
    if status == "FINISHED":
        return finished
    return f"({started} AND NOT {finished})"


def _text_clause(
    expression: str,
    condition: LibraryFilterCondition,
    key: str,
    params: SqlParams,
) -> str:
    normalized = f"lower(trim(coalesce({expression}, '')))"
    if condition.operator == "is_empty":
        return f"{normalized} = ''"
    if condition.operator == "is_not_empty":
        return f"{normalized} <> ''"
    value = str(condition.value or "").lower()
    if condition.operator in {"contains", "not_contains"}:
        params[key] = f"%{value}%"
        clause = f"{normalized} LIKE :{key}"
        return f"NOT ({clause})" if condition.operator == "not_contains" else clause
    if condition.operator == "starts_with":
        params[key] = f"{value}%"
        return f"{normalized} LIKE :{key}"
    if condition.operator == "ends_with":
        params[key] = f"%{value}"
        return f"{normalized} LIKE :{key}"
    params[key] = value
    clause = f"{normalized} = :{key}"
    return f"NOT ({clause})" if condition.operator == "not_equals" else clause


def _number_clause(
    expression: str,
    condition: LibraryFilterCondition,
    key: str,
    params: SqlParams,
) -> str:
    if condition.operator == "is_empty":
        return f"({expression}) IS NULL"
    if condition.operator == "is_not_empty":
        return f"({expression}) IS NOT NULL"
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        params[f"{key}_from"] = float(condition.value[0])
        params[f"{key}_to"] = float(condition.value[1])
        return f"({expression}) BETWEEN :{key}_from AND :{key}_to"
    operators = {
        "equals": "=",
        "not_equals": "<>",
        "greater_than": ">",
        "greater_or_equal": ">=",
        "less_than": "<",
        "less_or_equal": "<=",
    }
    params[key] = float(str(condition.value))
    return f"({expression}) {operators[condition.operator]} :{key}"


def _day_bounds(raw: str) -> tuple[datetime, datetime]:
    parsed = date.fromisoformat(raw)
    start = datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _date_clause(
    expression: str,
    condition: LibraryFilterCondition,
    key: str,
    params: SqlParams,
) -> str:
    if condition.operator == "is_empty":
        return f"({expression}) IS NULL"
    if condition.operator == "is_not_empty":
        return f"({expression}) IS NOT NULL"
    if condition.operator == "between":
        assert isinstance(condition.value, tuple)
        start, _ = _day_bounds(condition.value[0])
        _, end = _day_bounds(condition.value[1])
        params[f"{key}_from"] = start
        params[f"{key}_to"] = end
        return f"({expression}) >= :{key}_from AND ({expression}) < :{key}_to"
    start, end = _day_bounds(str(condition.value))
    params[f"{key}_start"] = start
    params[f"{key}_end"] = end
    if condition.operator == "equals":
        return f"({expression}) >= :{key}_start AND ({expression}) < :{key}_end"
    if condition.operator == "not_equals":
        return f"NOT (({expression}) >= :{key}_start AND ({expression}) < :{key}_end)"
    if condition.operator == "after":
        return f"({expression}) >= :{key}_end"
    if condition.operator == "on_or_after":
        return f"({expression}) >= :{key}_start"
    if condition.operator == "before":
        return f"({expression}) < :{key}_start"
    return f"({expression}) < :{key}_end"


def _relation_text_clause(
    base: str,
    expression: str,
    condition: LibraryFilterCondition,
    key: str,
    params: SqlParams,
) -> str:
    if condition.operator in {"not_equals", "is_empty"}:
        positive_operator = "equals" if condition.operator == "not_equals" else "is_not_empty"
        positive = _text_clause(
            expression,
            LibraryFilterCondition(
                field=condition.field,
                operator=positive_operator,
                value=condition.value,
            ),
            key,
            params,
        )
        return f"NOT EXISTS ({base} AND {positive})"
    predicate = _text_clause(expression, condition, key, params)
    return f"EXISTS ({base} AND {predicate})"


def condition_clause(
    condition: LibraryFilterCondition,
    index: int,
    params: SqlParams,
) -> str:
    key = f"filter_{index}"
    text_expressions = {
        "title": "w.title",
        "author": "w.author",
        "description": "w.summary",
        "series": "w.metadata ->> 'seriesName'",
    }
    if condition.field in text_expressions:
        return _text_clause(text_expressions[condition.field], condition, key, params)
    if condition.field in {"language", "format"}:
        base = (
            "SELECT 1 FROM catalog.editions AS filter_edition WHERE filter_edition.work_id = w.id"
        )
        return _relation_text_clause(
            base,
            f"filter_edition.{condition.field}",
            condition,
            key,
            params,
        )
    if condition.field == "readingStatus":
        if condition.operator == "is_empty":
            return "FALSE"
        if condition.operator == "is_not_empty":
            return "TRUE"
        clause = reading_status_clause(str(condition.value))
        return f"NOT ({clause})" if condition.operator == "not_equals" else clause
    if condition.field == "hasCover":
        clause = "w.cover_key IS NOT NULL"
        return f"NOT ({clause})" if condition.operator == "is_false" else clause
    if condition.field == "shelf":
        base = (
            "SELECT 1 FROM catalog.shelf_items AS filter_item "
            "JOIN catalog.shelves AS filter_shelf ON filter_shelf.id = filter_item.shelf_id "
            "WHERE filter_item.work_id = w.id "
            "AND filter_shelf.owner_id = :account_id "
            "AND filter_shelf.kind = 'manual'"
        )
        return _relation_text_clause(base, "filter_shelf.id::text", condition, key, params)
    numeric_expressions = {
        "fileSize": (
            "(SELECT sum(filter_file.size_bytes)::numeric / 1048576 "
            "FROM catalog.files AS filter_file "
            "JOIN catalog.editions AS filter_edition "
            "ON filter_edition.id = filter_file.edition_id "
            "WHERE filter_edition.work_id = w.id)"
        ),
        "pageCount": (
            "(SELECT max(filter_volume.page_count) FROM catalog.volumes AS filter_volume "
            "JOIN catalog.editions AS filter_edition "
            "ON filter_edition.id = filter_volume.edition_id "
            "WHERE filter_edition.work_id = w.id)"
        ),
        "duration": (
            "(SELECT max(coalesce(filter_volume.duration_ms, filter_file.duration_ms))::numeric "
            "/ 60000 FROM catalog.editions AS filter_edition "
            "LEFT JOIN catalog.volumes AS filter_volume "
            "ON filter_volume.edition_id = filter_edition.id "
            "LEFT JOIN catalog.files AS filter_file "
            "ON filter_file.edition_id = filter_edition.id "
            "WHERE filter_edition.work_id = w.id)"
        ),
        "versionCount": (
            "(SELECT count(*) FROM catalog.editions AS filter_edition "
            "WHERE filter_edition.work_id = w.id)"
        ),
        "progress": (
            "(SELECT max(filter_progress.percentage) * 100 "
            "FROM reading.progress AS filter_progress "
            "JOIN catalog.editions AS filter_edition "
            "ON filter_edition.id = filter_progress.edition_id "
            "WHERE filter_progress.user_id = :account_id "
            "AND filter_edition.work_id = w.id)"
        ),
    }
    if condition.field in numeric_expressions:
        return _number_clause(numeric_expressions[condition.field], condition, key, params)
    date_expressions = {
        "lastReadAt": (
            "(SELECT max(filter_progress.updated_at) "
            "FROM reading.progress AS filter_progress "
            "JOIN catalog.editions AS filter_edition "
            "ON filter_edition.id = filter_progress.edition_id "
            "WHERE filter_progress.user_id = :account_id "
            "AND filter_edition.work_id = w.id)"
        ),
        "createdAt": "w.created_at",
        "updatedAt": "w.updated_at",
    }
    return _date_clause(date_expressions[condition.field], condition, key, params)


def option(value: object, label: object, count: object | None = None) -> dict[str, object]:
    item: dict[str, object] = {"value": str(value), "label": str(label)}
    if count is not None:
        item["count"] = int(str(count))
    return item
