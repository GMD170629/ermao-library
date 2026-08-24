from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.imports.application.library_commands import (
    DeleteLibrary,
    PreparedLibraryDelete,
)
from app.modules.system.public import PreparedSystemEvent


class RecordingStore:
    def __init__(self, *, fail_delete: bool = False) -> None:
        self.fail_delete = fail_delete
        self.calls: list[str] = []

    def create(self, prepared: object) -> None:
        del prepared
        raise NotImplementedError

    def update(self, prepared: object) -> None:
        del prepared
        raise NotImplementedError

    def cancel_import_tasks(self, library_id: str) -> int:
        self.calls.append(f"cancel:{library_id}")
        return 3

    def delete(self, prepared: PreparedLibraryDelete) -> bool:
        self.calls.append(f"delete:{prepared.library_id}")
        if self.fail_delete:
            raise RuntimeError("delete failed")
        return True


class RecordingUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _prepared_delete() -> PreparedLibraryDelete:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return PreparedLibraryDelete(
        library_id="library-1",
        affected_user_ids=(),
        updated_at=now,
        event=PreparedSystemEvent(
            id="event-1",
            level="warning",
            source="library",
            actor_type="admin",
            actor_id="user-1",
            action="deleted",
            target_type="library",
            target_id="library-1",
            message="deleted",
            metadata={},
            created_at=now,
        ),
    )


def test_delete_library_cancels_import_tasks_before_deleting() -> None:
    store = RecordingStore()
    unit_of_work = RecordingUnitOfWork()

    deleted = DeleteLibrary(store, unit_of_work).execute(_prepared_delete())

    assert deleted is True
    assert store.calls == ["cancel:library-1", "delete:library-1"]
    assert unit_of_work.commits == 1
    assert unit_of_work.rollbacks == 0


def test_delete_library_rolls_back_task_cancellation_when_delete_fails() -> None:
    store = RecordingStore(fail_delete=True)
    unit_of_work = RecordingUnitOfWork()

    with pytest.raises(RuntimeError, match="delete failed"):
        DeleteLibrary(store, unit_of_work).execute(_prepared_delete())

    assert store.calls == ["cancel:library-1", "delete:library-1"]
    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1
