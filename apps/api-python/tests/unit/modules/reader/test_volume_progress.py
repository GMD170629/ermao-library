from datetime import UTC, datetime

from app.modules.reader.domain.volume_progress import (
    MediaKind,
    VolumeReadingState,
    choose_continue_volume_id,
    completed_for_available_volumes,
)


def _volume(
    volume_id: str,
    media_kind: MediaKind,
    sort_order: int,
    *,
    percent: int = 0,
    last_read_at: datetime | None = None,
    visible: bool = True,
    authorized: bool = True,
) -> VolumeReadingState:
    return VolumeReadingState(
        volume_id=volume_id,
        media_kind=media_kind,
        sort_order=sort_order,
        percent=percent,
        last_read_at=last_read_at,
        visible=visible,
        authorized=authorized,
    )


def test_completion_requires_every_available_volume_and_non_empty_projection() -> None:
    assert not completed_for_available_volumes([])
    assert not completed_for_available_volumes(
        [
            _volume("one", MediaKind.EBOOK, 0, percent=100),
            _volume("two", MediaKind.EBOOK, 1, percent=99),
        ]
    )
    assert completed_for_available_volumes(
        [
            _volume("one", MediaKind.EBOOK, 0, percent=100),
            _volume("hidden", MediaKind.EBOOK, 1, visible=False),
            _volume("denied", MediaKind.EBOOK, 2, authorized=False),
        ]
    )


def test_continue_uses_recent_media_then_first_unfinished_volume() -> None:
    older = datetime(2026, 7, 1, tzinfo=UTC)
    newer = datetime(2026, 7, 2, tzinfo=UTC)
    volumes = [
        _volume("ebook-2", MediaKind.EBOOK, 20, percent=20, last_read_at=older),
        _volume("ebook-1", MediaKind.EBOOK, 10, percent=0),
        _volume("comic-2", MediaKind.COMIC, 20, percent=0),
        _volume("comic-1", MediaKind.COMIC, 10, percent=0, last_read_at=newer),
    ]

    assert choose_continue_volume_id(volumes) == "comic-1"


def test_continue_falls_back_to_media_priority_without_history() -> None:
    volumes = [
        _volume("audio", MediaKind.AUDIOBOOK, 0),
        _volume("comic", MediaKind.COMIC, 0),
        _volume("ebook", MediaKind.EBOOK, 0),
    ]

    assert choose_continue_volume_id(volumes) == "ebook"


def test_all_complete_returns_latest_read_volume() -> None:
    volumes = [
        _volume(
            "ebook",
            MediaKind.EBOOK,
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        _volume(
            "audio",
            MediaKind.AUDIOBOOK,
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 3, tzinfo=UTC),
        ),
    ]

    assert choose_continue_volume_id(volumes) == "audio"
