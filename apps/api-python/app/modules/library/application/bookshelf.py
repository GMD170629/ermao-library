"""Application contracts for the user-scoped bookshelf projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.authorization import AuthorizationContext


@dataclass(frozen=True, slots=True)
class BookshelfItemSummary:
    id: str
    title: str
    author: str
    cover_path: str | None
    updated_at: datetime
    available_media_kinds: tuple[str, ...]
    progress: float


class BookshelfItemQueryPort(Protocol):
    def list_items(
        self,
        *,
        context: AuthorizationContext,
        work_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]: ...


@dataclass(frozen=True, slots=True)
class ListBookshelfItems:
    query: BookshelfItemQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        work_ids: tuple[str, ...],
    ) -> tuple[BookshelfItemSummary, ...]:
        normalized_ids = tuple(
            dict.fromkeys(work_id.strip() for work_id in work_ids if work_id.strip())
        )
        if len(normalized_ids) > 200:
            raise ValueError("bookshelf projection is limited to 200 works")
        if not normalized_ids:
            return ()
        return self.query.list_items(context=context, work_ids=normalized_ids)
