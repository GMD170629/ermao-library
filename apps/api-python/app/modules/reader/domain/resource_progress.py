"""Pure resource-scoped completion and continue-reading rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum


class MediaKind(StrEnum):
    EBOOK = "EBOOK"
    COMIC = "COMIC"
    AUDIOBOOK = "AUDIOBOOK"


_MEDIA_PRIORITY: dict[MediaKind, int] = {
    MediaKind.EBOOK: 0,
    MediaKind.COMIC: 1,
    MediaKind.AUDIOBOOK: 2,
}


@dataclass(frozen=True, slots=True)
class ResourceReadingState:
    resource_id: str
    media_kind: MediaKind
    sort_order: int
    percent: int = 0
    last_read_at: datetime | None = None
    visible: bool = True
    authorized: bool = True

    @property
    def available(self) -> bool:
        return self.visible and self.authorized

    @property
    def completed(self) -> bool:
        return self.percent >= 100


def completed_for_available_resources(resources: list[ResourceReadingState]) -> bool:
    """Return completion only when the non-empty authorized projection is done."""

    available = [resource for resource in resources if resource.available]
    return bool(available) and all(resource.completed for resource in available)


def choose_continue_resource_id(resources: list[ResourceReadingState]) -> str | None:
    """Choose a resource without inventing media- or book-level progress state."""

    available = [resource for resource in resources if resource.available]
    if not available:
        return None

    unfinished = [resource for resource in available if not resource.completed]
    if not unfinished:
        latest = max(
            available,
            key=lambda resource: (
                resource.last_read_at is not None,
                resource.last_read_at or datetime.min.replace(tzinfo=UTC),
                -_MEDIA_PRIORITY[resource.media_kind],
                -resource.sort_order,
                resource.resource_id,
            ),
        )
        return latest.resource_id

    media_last_read: dict[MediaKind, datetime | None] = {}
    for resource in available:
        latest_for_media = media_last_read.get(resource.media_kind)
        if resource.last_read_at is not None and (
            latest_for_media is None or resource.last_read_at > latest_for_media
        ):
            media_last_read[resource.media_kind] = resource.last_read_at

    unfinished_media = {resource.media_kind for resource in unfinished}

    def media_last_read_rank(media_kind: MediaKind) -> float:
        last_read_at = media_last_read.get(media_kind)
        return last_read_at.timestamp() if last_read_at is not None else float("-inf")

    selected_media = min(
        unfinished_media,
        key=lambda media_kind: (
            -media_last_read_rank(media_kind),
            _MEDIA_PRIORITY[media_kind],
        ),
    )
    first_unfinished = min(
        (resource for resource in unfinished if resource.media_kind == selected_media),
        key=lambda resource: (resource.sort_order, resource.resource_id),
    )
    return first_unfinished.resource_id
