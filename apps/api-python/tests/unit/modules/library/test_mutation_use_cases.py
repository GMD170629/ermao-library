from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.modules.library.application.asset_commands import (
    DeleteResourceAsset,
    ResourceAssetDeletion,
)
from app.modules.library.application.book_commands import UpdateBook, UpdateBookCommand
from app.modules.library.application.resource_cover import (
    RegenerateResourceCover,
    RegenerateResourceCoverCommand,
    ResourceCoverContext,
)


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


class CoverPort:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def get_context(
        self, *, book_id: str, resource_id: str
    ) -> ResourceCoverContext:
        return ResourceCoverContext(
            resource_id=resource_id,
            book_id=book_id,
            source_node_id="source-node",
        )

    def mark_pending(self, *, resource_id: str, now: datetime) -> None:
        self.events.append("mark_pending")


class Continuation:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def enqueue_source_import(self, source_node_id: str) -> str:
        self.events.append("enqueue")
        return "task-id"


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


def test_cover_regeneration_commits_before_source_enqueue() -> None:
    events: list[str] = []
    result = RegenerateResourceCover(
        CoverPort(events),
        Continuation(events),
        RecordingUnitOfWork(events),
    ).execute(
        RegenerateResourceCoverCommand(
            book_id="book-id",
            resource_id="resource-id",
            now=datetime.now(UTC),
        )
    )

    assert result.task_id == "task-id"
    assert events == ["mark_pending", "commit", "enqueue"]


def test_asset_deletion_marks_resource_failed_when_ready_assets_reach_zero() -> None:
    events: list[str] = []
    result = DeleteResourceAsset(
        AssetPort(events), RecordingUnitOfWork(events)
    ).execute(asset_id="asset-id")

    assert result.asset_id == "asset-id"
    assert result.deleted is True
    assert events == ["delete", "mark_failed", "commit"]
