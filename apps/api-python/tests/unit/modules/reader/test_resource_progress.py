from datetime import UTC, datetime

from app.modules.reader.domain.resource_progress import (
    MediaKind,
    ResourceReadingState,
    choose_continue_resource_id,
    completed_for_available_resources,
)


def _resource(
    resource_id: str,
    media_kind: MediaKind,
    sort_order: int,
    *,
    percent: int = 0,
    last_read_at: datetime | None = None,
    visible: bool = True,
    authorized: bool = True,
) -> ResourceReadingState:
    return ResourceReadingState(
        resource_id=resource_id,
        media_kind=media_kind,
        sort_order=sort_order,
        percent=percent,
        last_read_at=last_read_at,
        visible=visible,
        authorized=authorized,
    )


def test_completion_requires_every_available_resource_and_non_empty_projection() -> (
    None
):
    assert not completed_for_available_resources([])
    assert not completed_for_available_resources(
        [
            _resource("one", MediaKind.EBOOK, 0, percent=100),
            _resource("two", MediaKind.EBOOK, 1, percent=99),
        ]
    )
    assert completed_for_available_resources(
        [
            _resource("one", MediaKind.EBOOK, 0, percent=100),
            _resource("hidden", MediaKind.EBOOK, 1, visible=False),
            _resource("denied", MediaKind.EBOOK, 2, authorized=False),
        ]
    )


def test_continue_uses_recent_media_then_first_unfinished_resource() -> None:
    older = datetime(2026, 7, 1, tzinfo=UTC)
    newer = datetime(2026, 7, 2, tzinfo=UTC)
    resources = [
        _resource("ebook-2", MediaKind.EBOOK, 20, percent=20, last_read_at=older),
        _resource("ebook-1", MediaKind.EBOOK, 10, percent=0),
        _resource("comic-2", MediaKind.COMIC, 20, percent=0),
        _resource("comic-1", MediaKind.COMIC, 10, percent=0, last_read_at=newer),
    ]

    assert choose_continue_resource_id(resources) == "comic-1"


def test_continue_falls_back_to_media_priority_without_history() -> None:
    resources = [
        _resource("audio", MediaKind.AUDIOBOOK, 0),
        _resource("comic", MediaKind.COMIC, 0),
        _resource("ebook", MediaKind.EBOOK, 0),
    ]

    assert choose_continue_resource_id(resources) == "ebook"


def test_all_complete_returns_latest_read_resource() -> None:
    resources = [
        _resource(
            "ebook",
            MediaKind.EBOOK,
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        _resource(
            "audio",
            MediaKind.AUDIOBOOK,
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 3, tzinfo=UTC),
        ),
    ]

    assert choose_continue_resource_id(resources) == "audio"
