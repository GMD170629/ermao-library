"""Application queries for the three user-facing dashboard capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.core.authorization import AuthorizationContext
from app.modules.library.application.bookshelf import (
    BookshelfItemQueryPort,
    BookshelfItemSummary,
)


@dataclass(frozen=True, slots=True)
class DashboardContinueReading:
    book_id: str
    title: str
    author: str
    media_kind: Literal["EBOOK", "COMIC", "AUDIOBOOK"]
    resource_format: str
    reader_type: Literal["reflowable", "comic", "pdf", "audio"]
    resource_id: str
    resource_title: str
    narrator: str | None
    progress: float
    updated_at: datetime | None


class DashboardActivityQueryPort(Protocol):
    def recent_book_ids(
        self,
        *,
        context: AuthorizationContext,
        limit: int,
    ) -> tuple[str, ...]: ...

    def recent_reading_book_ids(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        limit: int,
    ) -> tuple[str, ...]: ...

    def continue_reading(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
    ) -> DashboardContinueReading | None: ...


@dataclass(frozen=True, slots=True)
class DashboardQueries:
    activity: DashboardActivityQueryPort
    bookshelf: BookshelfItemQueryPort

    @staticmethod
    def _limit(value: int) -> int:
        if not 1 <= value <= 50:
            raise ValueError("dashboard limit must be between 1 and 50")
        return value

    def recent_books(
        self,
        *,
        context: AuthorizationContext,
        limit: int,
    ) -> tuple[BookshelfItemSummary, ...]:
        book_ids = self.activity.recent_book_ids(
            context=context,
            limit=self._limit(limit),
        )
        return self.bookshelf.list_items(context=context, book_ids=book_ids)

    def recent_reading(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        limit: int,
    ) -> tuple[BookshelfItemSummary, ...]:
        book_ids = self.activity.recent_reading_book_ids(
            context=context,
            user_id=user_id,
            limit=self._limit(limit),
        )
        return self.bookshelf.list_items(context=context, book_ids=book_ids)

    def continue_reading(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
    ) -> DashboardContinueReading | None:
        return self.activity.continue_reading(context=context, user_id=user_id)


__all__ = [
    "DashboardActivityQueryPort",
    "DashboardContinueReading",
    "DashboardQueries",
]
