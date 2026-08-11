from datetime import UTC, datetime

from app.bootstrap.imports import (
    clear_import_queue_records,
    persist_import_queue_operation_checkpoint,
)
from app.models.auth import User
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportLog,
    ImportTask,
)
from app.models.library import LibraryMediaVersion, LibraryVolume, LibraryWork
from app.models.settings import QueueControlOperation, SystemEvent
from app.modules.imports.application.queue_control import (
    PreparedImportQueueOperationCheckpoint,
)
from app.services.system_events import prepare_system_event
from sqlalchemy import func, select


def test_clear_import_queue_deletes_every_status_and_preserves_content(
    db_session,
    test_settings,
):
    source_file = test_settings.resolved_monitor_root / "preserved-source.epub"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"source")
    work = LibraryWork(
        id="preserved-work",
        title="Preserved",
        normalized_title="preserved",
        tags="[]",
    )
    media_version = LibraryMediaVersion(
        id="preserved-media",
        work_id=work.id,
        media_kind="EBOOK",
    )
    volume = LibraryVolume(
        id="preserved-volume",
        media_version_id=media_version.id,
        title="Preserved source",
        sort_order=0,
        format="MOBI",
        resource_key="test:preserved-volume",
        import_status="COMPLETED",
    )
    db_session.add_all([work, media_version, volume])
    for status in ("PENDING", "PARSING", "COMPLETED", "FAILED"):
        db_session.add(
            ImportTask(
                id=f"clear-{status.lower()}",
                work_id=work.id if status == "COMPLETED" else None,
                volume_id=volume.id if status == "COMPLETED" else None,
                origin="MANUAL",
                status=status,
                source_path=str(source_file),
            )
        )
    db_session.flush()
    db_session.add_all(
        [
            ImportAsset(
                id="clear-asset",
                import_task_id="clear-pending",
                source_path=str(source_file),
            ),
            ImportLog(
                id="clear-log",
                import_task_id="clear-parsing",
                message="processing",
            ),
            BookConversionTask(
                id="clear-conversion",
                import_task_id="clear-completed",
                source_volume_id=volume.id,
                idempotency_key="test:clear-conversion",
                source_format="MOBI",
                source_path=str(source_file),
            ),
        ]
    )
    db_session.commit()

    deleted = clear_import_queue_records(db_session)

    assert deleted == 4
    assert db_session.scalar(select(func.count()).select_from(ImportTask)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportAsset)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportLog)) == 0
    assert db_session.scalar(select(func.count()).select_from(BookConversionTask)) == 0
    assert db_session.get(LibraryWork, work.id) is not None
    assert source_file.read_bytes() == b"source"


class _FakeMaintenanceStore:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure

    def delete_all_tasks(self) -> int:
        if self.failure is not None:
            raise self.failure
        return 3


class _FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_clear_import_queue_rolls_back_when_deletion_fails():
    from app.modules.imports.application.clear_queue import clear_import_queue

    unit_of_work = _FakeUnitOfWork()

    try:
        clear_import_queue(
            _FakeMaintenanceStore(failure=RuntimeError("delete failed")),
            unit_of_work,
        )
    except RuntimeError as exc:
        assert str(exc) == "delete failed"
    else:
        raise AssertionError("clear_import_queue should preserve the failure")

    assert unit_of_work.commits == 0
    assert unit_of_work.rollbacks == 1


def test_queue_completion_status_and_event_share_one_checkpoint(db_session) -> None:
    checkpoint_at = datetime.now(UTC)
    user = User(
        id="queue-checkpoint-user",
        email="queue-checkpoint@example.com",
        name="Queue Checkpoint",
        password_hash="test",
        role="admin",
    )
    operation = QueueControlOperation(
        id="queue-checkpoint",
        queue_name="import",
        action="clear",
        status="running",
        actor_user_id=user.id,
        message_code="queue.clear.running",
        requested_at=checkpoint_at,
        started_at=checkpoint_at,
        finished_at=None,
        updated_at=checkpoint_at,
    )
    db_session.add_all([user, operation])
    db_session.commit()
    event = prepare_system_event(
        event_id="queue-checkpoint-event",
        created_at=checkpoint_at,
        source="system",
        action="queue.cleared",
        message="queue cleared",
    )

    persist_import_queue_operation_checkpoint(
        db_session,
        PreparedImportQueueOperationCheckpoint(
            operation_id=operation.id,
            status="completed",
            message_code="queue.clear.completed",
            checkpoint_at=checkpoint_at,
            events=(event,),
        ),
    )

    db_session.refresh(operation)
    assert operation.status == "completed"
    assert operation.message_code == "queue.clear.completed"
    assert db_session.get(SystemEvent, event.id) is not None
