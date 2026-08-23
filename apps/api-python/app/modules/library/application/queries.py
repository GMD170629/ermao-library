from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.library.application.filter_ast import (
    FilterExpression,
    parse_filter_expression,
)


def _strings(value: object, *, upper: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for raw in value:
        item = str(raw).strip()
        if upper:
            item = item.upper()
        if item and item not in result:
            result.append(item)
    return tuple(result)


@dataclass(frozen=True)
class SmartShelfCriteria:
    search: str
    statuses: tuple[str, ...]
    tags: tuple[str, ...]
    authors: tuple[str, ...]
    included_book_ids: tuple[str, ...]
    filters: FilterExpression

    @classmethod
    def from_external(cls, value: object) -> SmartShelfCriteria:
        if not isinstance(value, dict):
            raise TypeError("智能书架规则格式不正确")
        statuses = tuple(
            item
            for item in _strings(value.get("statuses"), upper=True)
            if item in {"UNREAD", "READING", "FINISHED"}
        )
        return cls(
            search=str(value.get("search") or "").strip(),
            statuses=statuses,
            tags=_strings(value.get("tags")),
            authors=_strings(value.get("authors")),
            included_book_ids=_strings(value.get("includedBookIds")),
            filters=parse_filter_expression(
                {
                    "combinator": value.get("combinator", "ALL"),
                    "conditions": value.get("conditions") or [],
                }
            ),
        )


class SmartShelfQueryPort(Protocol):
    def matching_book_ids(
        self,
        criteria: SmartShelfCriteria,
        *,
        user_id: str | None,
    ) -> list[str]: ...


@dataclass(frozen=True)
class GetSmartShelfBookIds:
    query: SmartShelfQueryPort

    def execute(
        self,
        criteria: SmartShelfCriteria,
        *,
        user_id: str | None,
    ) -> list[str]:
        return self.query.matching_book_ids(criteria, user_id=user_id)
