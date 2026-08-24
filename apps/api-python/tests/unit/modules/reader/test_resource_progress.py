from datetime import UTC, datetime

from app.modules.reader.domain.resource_progress import (
    ResourceReadingState,
    choose_continue_resource_id,
    completed_for_available_resources,
)


def _resource(
    resource_id: str,
    sort_order: int,
    *,
    percent: int = 0,
    last_read_at: datetime | None = None,
    visible: bool = True,
    authorized: bool = True,
) -> ResourceReadingState:
    return ResourceReadingState(
        resource_id=resource_id,
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
            _resource("one", 0, percent=100),
            _resource("two", 1, percent=99),
        ]
    )
    assert completed_for_available_resources(
        [
            _resource("one", 0, percent=100),
            _resource("hidden", 1, visible=False),
            _resource("denied", 2, authorized=False),
        ]
    )


def test_continue_uses_most_recent_unfinished_resource() -> None:
    older = datetime(2026, 7, 1, tzinfo=UTC)
    newer = datetime(2026, 7, 2, tzinfo=UTC)
    resources = [
        _resource("resource-2", 20, percent=20, last_read_at=older),
        _resource("resource-1", 10, percent=0),
        _resource("resource-4", 40, percent=0),
        _resource("resource-3", 30, percent=0, last_read_at=newer),
    ]

    assert choose_continue_resource_id(resources) == "resource-3"


def test_continue_falls_back_to_resource_order_without_history() -> None:
    resources = [
        _resource("third", 30),
        _resource("second", 20),
        _resource("first", 10),
    ]

    assert choose_continue_resource_id(resources) == "first"


def test_all_complete_returns_latest_read_resource() -> None:
    resources = [
        _resource(
            "first",
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        _resource(
            "second",
            0,
            percent=100,
            last_read_at=datetime(2026, 7, 3, tzinfo=UTC),
        ),
    ]

    assert choose_continue_resource_id(resources) == "second"
