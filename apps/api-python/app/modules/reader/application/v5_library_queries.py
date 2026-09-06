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
from app.modules.reader.application.v5_dto import ReaderV5PresentationDto
from app.modules.reader.domain.resource_progress import ResourceReadingState


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
    chapter_navigation_key: str | None = None
    presentation: ReaderV5PresentationDto | None = None


@dataclass(frozen=True, slots=True)
class ReaderV5StatusView:
    resource_id: str
    status: Literal["UNREAD", "FINISHED"]
    updated_at: datetime


def resource_reading_state(
    *,
    resource_id: str,
    sort_order: int,
    presentation: ReaderV5PresentationView | None,
    status: ReaderV5StatusView | None,
) -> ResourceReadingState:
    """Combine actor-scoped display and explicit status through the domain owner."""

    return ResourceReadingState(
        resource_id=resource_id,
        sort_order=sort_order,
        percent=min(100.0, max(0.0, presentation.display_percent))
        if presentation
        else 0,
        last_read_at=presentation.updated_at if presentation else None,
        explicit_status=status.status if status else None,
    )


class ReaderReadingStateQueryPort(Protocol):
    """Actor-scoped reading state shared by Reader and Library projections."""

    def list_reading_states(
        self, *, user_id: str, resource_ids: Sequence[str]
    ) -> Mapping[str, ResourceReadingState]: ...


class ReaderV5LibraryPresentationQueryPort(ReaderReadingStateQueryPort, Protocol):
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
