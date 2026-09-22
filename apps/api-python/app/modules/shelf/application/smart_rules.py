"""Shared smart-shelf normalization for HTTP and automation callers."""

from collections.abc import Callable
from typing import Any


def normalize_smart_shelf_rules(
    value: Any,
    *,
    normalize_filter_rules: Callable[[object], tuple[dict[str, Any], str | None]],
) -> tuple[dict[str, Any], str | None]:
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
