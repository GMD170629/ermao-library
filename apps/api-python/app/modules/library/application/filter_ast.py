from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

FilterCombinator = Literal["ALL", "ANY"]

TEXT_OPERATORS = frozenset(
    {
        "contains",
        "not_contains",
        "equals",
        "not_equals",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
    }
)
SELECT_OPERATORS = frozenset({"equals", "not_equals", "is_empty", "is_not_empty"})
NUMBER_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "between",
        "is_empty",
        "is_not_empty",
    }
)
DATE_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "after",
        "on_or_after",
        "before",
        "on_or_before",
        "between",
        "is_empty",
        "is_not_empty",
    }
)
BOOLEAN_OPERATORS = frozenset({"is_true", "is_false"})
FIELD_OPERATORS = {
    **{
        field: TEXT_OPERATORS
        for field in (
            "title",
            "description",
            "volumeTitle",
            "narrator",
            "sourcePath",
        )
    },
    **{
        field: SELECT_OPERATORS
        for field in (
            "author",
            "tag",
            "series",
            "mediaKind",
            "format",
            "readingStatus",
            "publicationStatus",
            "trackingStatus",
            "organizeStatus",
            "shelf",
            "library",
            "origin",
            "importStatus",
        )
    },
    **{
        field: NUMBER_OPERATORS
        for field in (
            "seriesIndex",
            "metadataQuality",
            "fileSize",
            "pageCount",
            "chapterCount",
            "duration",
            "resourceCount",
            "progress",
        )
    },
    **{field: DATE_OPERATORS for field in ("lastReadAt", "createdAt", "updatedAt")},
    **{field: BOOLEAN_OPERATORS for field in ("organized", "hasCover")},
}


@dataclass(frozen=True)
class FilterCondition:
    field: str
    operator: str
    value: str | tuple[str, str] | None = None


@dataclass(frozen=True)
class FilterExpression:
    combinator: FilterCombinator
    conditions: tuple[FilterCondition, ...]


class InvalidFilterExpression(ValueError):
    pass


def parse_filter_expression(value: object) -> FilterExpression:
    if value in (None, ""):
        return FilterExpression(combinator="ALL", conditions=())
    if not isinstance(value, dict):
        raise InvalidFilterExpression("筛选规则格式不正确")
    raw_combinator = value.get("combinator")
    combinator = str(raw_combinator or "ALL").upper()
    if combinator not in {"ALL", "ANY"}:
        raise InvalidFilterExpression("筛选条件组合方式无效")
    raw_conditions = value.get("conditions") or []
    if not isinstance(raw_conditions, list):
        raise InvalidFilterExpression("筛选条件格式不正确")
    if len(raw_conditions) > 30:
        raise InvalidFilterExpression("筛选条件最多支持 30 条")
    conditions: list[FilterCondition] = []
    for raw in raw_conditions:
        if not isinstance(raw, dict):
            raise InvalidFilterExpression("筛选条件格式不正确")
        field_key = str(raw.get("field") or "").strip()
        operators = FIELD_OPERATORS.get(field_key)
        if operators is None:
            raise InvalidFilterExpression(f"不支持的筛选维度：{field_key or '空'}")
        operator = str(raw.get("operator") or "").strip()
        if operator not in operators:
            raise InvalidFilterExpression(f"{field_key}不支持这个条件")
        condition_value: str | tuple[str, str] | None = None
        if operator not in {"is_empty", "is_not_empty", "is_true", "is_false"}:
            raw_value = raw.get("value")
            if operator == "between":
                if (
                    not isinstance(raw_value, list)
                    or len(raw_value) != 2
                    or any(not str(item).strip() for item in raw_value)
                ):
                    raise InvalidFilterExpression(f"请填写{field_key}的完整范围")
                condition_value = (str(raw_value[0]).strip(), str(raw_value[1]).strip())
            else:
                normalized_value = str(
                    raw_value if raw_value is not None else ""
                ).strip()
                if not normalized_value:
                    raise InvalidFilterExpression(f"请填写{field_key}的筛选值")
                condition_value = normalized_value[:500]
        conditions.append(
            FilterCondition(
                field=field_key,
                operator=operator,
                value=condition_value,
            )
        )
    return FilterExpression(
        combinator=cast(FilterCombinator, combinator),
        conditions=tuple(conditions),
    )
