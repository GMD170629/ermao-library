"""Application DTOs for the opaque Reader v5 progress contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from app.modules.reader.application.dto import (
    ReaderAssetDto,
    ReaderNavigationUnitDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)
from app.modules.reader.application.v5_locator import OpaqueLocator

if TYPE_CHECKING:
    from app.modules.reader.application.v5_position import ReaderV5StoredPosition


def _require_text(value: str, *, name: str, max_length: int) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(
            f"{name} must be a non-blank string of at most {max_length} characters"
        )


def _require_optional_text(value: str | None, *, name: str, max_length: int) -> None:
    if value is not None and (not isinstance(value, str) or len(value) > max_length):
        raise ValueError(f"{name} exceeds its maximum length")


def _require_nonnegative_int(value: int, *, name: str, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _require_optional_nonnegative_int(
    value: int | None, *, name: str, minimum: int = 0
) -> None:
    if value is not None:
        _require_nonnegative_int(value, name=name, minimum=minimum)


def _require_finite_range(
    value: float, *, name: str, minimum: float, maximum: float
) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < minimum
        or float(value) > maximum
    ):
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")


def _require_uuid(value: str, *, name: str) -> None:
    try:
        UUID(value)
    except (AttributeError, ValueError, TypeError) as error:
        raise ValueError(f"{name} must be a UUID") from error


@dataclass(frozen=True, slots=True)
class ReaderV5ChapterDto:
    href: str | None
    title: str | None
    index: int | None

    def __post_init__(self) -> None:
        _require_optional_text(self.href, name="chapter.href", max_length=8192)
        _require_optional_text(self.title, name="chapter.title", max_length=4096)
        _require_optional_nonnegative_int(self.index, name="chapter.index")


@dataclass(frozen=True, slots=True)
class ReaderV5PageDto:
    number: int
    total: int | None

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.number, name="page.number", minimum=1)
        _require_optional_nonnegative_int(self.total, name="page.total", minimum=1)


@dataclass(frozen=True, slots=True)
class ReaderV5PlaybackDto:
    position_millis: int
    duration_millis: int | None

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.position_millis, name="playback.position_millis")
        _require_optional_nonnegative_int(
            self.duration_millis, name="playback.duration_millis"
        )


@dataclass(frozen=True, slots=True)
class ReaderV5PresentationDto:
    display_percent: float
    total_progression: float
    current_href: str | None
    chapter: ReaderV5ChapterDto | None
    page: ReaderV5PageDto | None
    playback: ReaderV5PlaybackDto | None

    def __post_init__(self) -> None:
        _require_finite_range(
            self.display_percent,
            name="presentation.display_percent",
            minimum=0,
            maximum=100,
        )
        _require_finite_range(
            self.total_progression,
            name="presentation.total_progression",
            minimum=0,
            maximum=1,
        )
        _require_optional_text(
            self.current_href, name="presentation.current_href", max_length=8192
        )


@dataclass(frozen=True, slots=True)
class ReaderV5PositionDto:
    """The opaque Locator value and its independent client presentation."""

    locator: OpaqueLocator
    presentation: ReaderV5PresentationDto


@dataclass(frozen=True, slots=True)
class ReaderV5ProgressDto:
    id: str
    user_id: str
    resource_id: str
    client_id: str
    mutation_id: str
    revision: int
    position: ReaderV5PositionDto
    captured_at: datetime
    received_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.client_id, name="client_id", max_length=256)
        _require_uuid(self.mutation_id, name="mutation_id")
        _require_nonnegative_int(self.revision, name="revision", minimum=1)


@dataclass(frozen=True, slots=True)
class ReaderV5MutationDto:
    """Previously accepted payload receipt used for idempotency replay.

    A receipt is only an acknowledgement record.  The current progress table
    is the sole source for replay response snapshots, so the receipt never
    stores a Locator or presentation copy.
    """

    mutation_id: str
    client_id: str
    accepted_revision: int
    payload_hash: str
    captured_at: datetime
    received_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.client_id, name="client_id", max_length=256)
        _require_uuid(self.mutation_id, name="mutation_id")
        _require_nonnegative_int(
            self.accepted_revision, name="accepted_revision", minimum=1
        )
        if len(self.payload_hash) != 64:
            raise ValueError("payload_hash must be a SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class ReaderV5BookmarkInputDto:
    """Validated bookmark submission before opaque position serialization."""

    bookmark_id: str
    position: ReaderV5PositionDto
    label: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bookmark_id, str)
            or not self.bookmark_id
            or len(self.bookmark_id) > 5000
        ):
            raise ValueError("bookmark_id must contain 1..5000 characters")
        if not isinstance(self.label, str) or len(self.label) > 500:
            raise ValueError("bookmark label exceeds 500 characters")


@dataclass(frozen=True, slots=True)
class ReaderV5StoredBookmarkDto:
    """Bookmark value handed to the ORM after one authoritative serialization."""

    bookmark_id: str
    stored_position: ReaderV5StoredPosition
    label: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReaderV5BookmarkDto:
    bookmark_id: str
    position: ReaderV5PositionDto
    label: str
    created_at: datetime

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bookmark_id, str)
            or not self.bookmark_id
            or len(self.bookmark_id) > 5000
        ):
            raise ValueError("bookmark_id must contain 1..5000 characters")
        if not isinstance(self.label, str) or len(self.label) > 500:
            raise ValueError("bookmark label exceeds 500 characters")


@dataclass(frozen=True, slots=True)
class ReaderV5ReadingStatusDto:
    resource_id: str
    status: Literal["UNREAD", "FINISHED"]
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.status not in {"UNREAD", "FINISHED"}:
            raise ValueError("invalid Reader v5 reading status")


@dataclass(frozen=True, slots=True)
class ReaderV5BootstrapDto:
    context: ReaderResourceContextDto
    available_resources: tuple[ReaderResourceDto, ...]
    assets: tuple[ReaderAssetDto, ...]
    units: tuple[ReaderNavigationUnitDto, ...]
    progress: ReaderV5ProgressDto | None
    progress_by_resource_id: dict[str, ReaderV5ProgressDto]
