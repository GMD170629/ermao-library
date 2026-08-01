"""Pure volume-scoped completion and continue-reading rules."""

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
class VolumeReadingState:
    volume_id: str
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


def completed_for_available_volumes(volumes: list[VolumeReadingState]) -> bool:
    """Return completion only when the non-empty authorized projection is done."""

    available = [volume for volume in volumes if volume.available]
    return bool(available) and all(volume.completed for volume in available)


def choose_continue_volume_id(volumes: list[VolumeReadingState]) -> str | None:
    """Choose a volume without inventing media- or work-level progress state."""

    available = [volume for volume in volumes if volume.available]
    if not available:
        return None

    unfinished = [volume for volume in available if not volume.completed]
    if not unfinished:
        latest = max(
            available,
            key=lambda volume: (
                volume.last_read_at is not None,
                volume.last_read_at or datetime.min.replace(tzinfo=UTC),
                -_MEDIA_PRIORITY[volume.media_kind],
                -volume.sort_order,
                volume.volume_id,
            ),
        )
        return latest.volume_id

    media_last_read: dict[MediaKind, datetime | None] = {}
    for volume in available:
        latest_for_media = media_last_read.get(volume.media_kind)
        if volume.last_read_at is not None and (
            latest_for_media is None or volume.last_read_at > latest_for_media
        ):
            media_last_read[volume.media_kind] = volume.last_read_at

    unfinished_media = {volume.media_kind for volume in unfinished}

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
        (volume for volume in unfinished if volume.media_kind == selected_media),
        key=lambda volume: (volume.sort_order, volume.volume_id),
    )
    return first_unfinished.volume_id
