"""Public Reader queries consumed by Library projections.

Library must not know the storage shape of the Reader v5 aggregate.  This
module is the stable capability boundary: it exposes presentation/status
projections and named query selectors while keeping the v5 ORM adapter
private to Reader infrastructure.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from app.core.authorization import AuthorizationContext


@dataclass(frozen=True, slots=True)
class ReaderV5PresentationView:
    """The client-authored presentation projection used by Library views."""

    resource_id: str
    display_percent: float
    total_progression: float
    current_href: str | None
    chapter_href: str | None
    chapter_title: str | None
    chapter_index: int | None
    page_number: int | None
    page_total: int | None
    playback_position_millis: int | None
    playback_duration_millis: int | None
    captured_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderV5StatusView:
    resource_id: str
    status: Literal["UNREAD", "FINISHED"]
    updated_at: datetime


class ReaderV5LibraryPresentationQueryPort(Protocol):
    """Reader-owned query API for Library's display and filter projections."""

    def list_presentations(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ReaderV5PresentationView]: ...

    def get_presentation(
        self, *, user_id: str, resource_id: str
    ) -> ReaderV5PresentationView | None: ...

    def latest_progress_at(self, *, user_id: str) -> datetime | None: ...

    def latest_read_at_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        book_id_expression: object,
    ) -> object: ...

    def progress_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str | None,
        book_id_expression: object,
        field: Literal["display_percent", "updated_at"],
    ) -> object: ...

    def reading_status_expression(
        self,
        *,
        context: AuthorizationContext,
        user_id: str,
        book_id_expression: object,
        status: str,
    ) -> object: ...

    def list_statuses(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ReaderV5StatusView]: ...

    def upsert_statuses(
        self,
        *,
        user_id: str,
        resource_ids: Sequence[str],
        status: str,
        updated_at: datetime,
    ) -> None: ...


__all__ = [
    "ReaderV5LibraryPresentationQueryPort",
    "ReaderV5PresentationView",
    "ReaderV5StatusView",
]
