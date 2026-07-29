"""Application contracts for browsing author and series groupings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.authorization import AuthorizationContext

LIBRARY_GROUPING_KINDS = frozenset({"AUTHOR", "SERIES"})


@dataclass(frozen=True)
class LibraryGrouping:
    id: str
    name: str
    normalized_name: str
    book_count: int
    updated_at: datetime


@dataclass(frozen=True)
class LibraryGroupingPage:
    groups: tuple[LibraryGrouping, ...]
    total: int


class LibraryGroupingQueryPort(Protocol):
    def list_groupings(
        self,
        *,
        kind: str,
        context: AuthorizationContext,
        search: str,
        page: int,
        page_size: int,
    ) -> LibraryGroupingPage: ...


@dataclass(frozen=True)
class ListLibraryGroupings:
    query: LibraryGroupingQueryPort

    def execute(
        self,
        *,
        kind: str,
        context: AuthorizationContext,
        search: str,
        page: int,
        page_size: int,
    ) -> LibraryGroupingPage:
        normalized_kind = kind.strip().upper()
        if normalized_kind not in LIBRARY_GROUPING_KINDS:
            raise ValueError("分组类型无效")
        return self.query.list_groupings(
            kind=normalized_kind,
            context=context,
            search=search.strip(),
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )
