from __future__ import annotations

from collections.abc import Mapping

from app.modules.library.application.asset_commands import (
    DeleteResourceAsset,
    ResourceAssetDeletion,
)
from app.modules.library.application.book_commands import UpdateBook, UpdateBookCommand


class RecordingUnitOfWork:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


class BookPort:
    def update_book(
        self, *, book_id: str, values: Mapping[str, object]
    ) -> Mapping[str, object]:
        return {"id": book_id, **values}


class AssetPort:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def delete_asset(self, *, asset_id: str) -> ResourceAssetDeletion:
        self.events.append("delete")
        return ResourceAssetDeletion(
            asset_id=asset_id,
            resource_id="resource-id",
            ready_asset_count=0,
        )

    def mark_resource_failed(self, *, resource_id: str) -> None:
        self.events.append("mark_failed")


def test_update_book_commits_through_its_unit_of_work() -> None:
    events: list[str] = []
    result = UpdateBook(BookPort(), RecordingUnitOfWork(events)).execute(
        UpdateBookCommand(book_id="book-id", values={"title": "Book"})
    )

    assert result == {"id": "book-id", "title": "Book"}
    assert events == ["commit"]


def test_asset_deletion_marks_resource_failed_when_ready_assets_reach_zero() -> None:
    events: list[str] = []
    result = DeleteResourceAsset(
        AssetPort(events), RecordingUnitOfWork(events)
    ).execute(asset_id="asset-id")

    assert result.asset_id == "asset-id"
    assert result.deleted is True
    assert events == ["delete", "mark_failed", "commit"]
