"""Application contracts for library work listing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkListQuery:
    page: int
    page_size: int
    visibility: str = "active"
    search: str | None = None
    keyword: str | None = None
    series_name: str | None = None
    sort: str = "updated"
    sort_direction: str | None = None
    type_filter: str = ""
    media_kinds: tuple[str, ...] = ()
    status: str | None = None
    publication_status: str | None = None
    tracking_status: str | None = None
    tag: str | None = None
    missing_cover: bool = False
    new_import: bool = False
    filter_rules: dict[str, Any] | None = None


@dataclass(frozen=True)
class WorkListResult:
    works: list[dict[str, Any]]
    total: int
    page: int
    page_size: int
    progress_sort: bool = False


def parse_media_kinds(raw: str) -> tuple[str, ...]:
    kinds: list[str] = []
    for raw_kind in raw.split(","):
        kind = raw_kind.strip().upper()
        if kind in {"EBOOK", "COMIC", "AUDIOBOOK"} and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)
