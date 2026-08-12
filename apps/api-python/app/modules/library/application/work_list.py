"""Application contracts for library work listing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.modules.library.application.filter_ast import FilterExpression

MAX_LIBRARY_PAGE_SIZE = 500


@dataclass(frozen=True)
class WorkListQuery:
    page: int
    requested_page_size: int | None
    visibility: str = "active"
    search: str | None = None
    keyword: str | None = None
    series_name: str | None = None
    facet_kind: str | None = None
    facet_id: str | None = None
    sort: str = "updated"
    sort_direction: str | None = None
    type_filter: str = ""
    media_kinds: tuple[str, ...] = ()
    status: str | None = None
    statuses: tuple[str, ...] = ()
    publication_status: str | None = None
    tracking_status: str | None = None
    tag: str | None = None
    missing_cover: bool = False
    new_import: bool = False
    filter_expression: FilterExpression | None = None


@dataclass(frozen=True)
class WorkListResult:
    works: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    progress_sort: bool = False


def resolve_page_size(requested_page_size: int | None, total: int) -> int:
    if requested_page_size is None:
        return max(1, total)
    return min(MAX_LIBRARY_PAGE_SIZE, max(1, requested_page_size))


def parse_media_kinds(raw: str) -> tuple[str, ...]:
    kinds: list[str] = []
    for raw_kind in raw.split(","):
        kind = raw_kind.strip().upper()
        if kind in {"EBOOK", "COMIC", "AUDIOBOOK"} and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)
