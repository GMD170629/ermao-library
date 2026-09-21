import pytest

from app.models import Library
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import FileMoveError, MoveRequest
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from tests.integration.modules.automation.test_file_reads import file_access


def test_scoped_complete_directory_plan_preserves_identity_and_is_pure(
    db_session, tmp_path
):
    access, root = file_access(db_session, tmp_path)
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    db_session.commit()
    (root / "allowed/metadata.opf").write_bytes(b"keep exactly")
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    topology = SqlAlchemyMoveTopology(db_session)
    prepare = PrepareFileMovePlan(
        topology, AnchoredMoveInspection(), lambda: 1000, lambda: "plan"
    )
    source = topology.source("allowed-node", actor.library_ids)
    plan = prepare.execute(
        actor, (MoveRequest("allowed-node", "test-library", "renamed"),)
    )
    assert plan.moves[0].source.book_ids == ("allowed",)
    assert plan.moves[0].source.revision == source.revision
    assert plan.moves[0].inventory.byte_count == 12
    assert (root / "allowed/metadata.opf").read_bytes() == b"keep exactly"
    assert not (root / "renamed").exists()
    with pytest.raises(FileMoveError, match="BOOK_OWNERSHIP_WOULD_CHANGE"):
        prepare.execute(
            actor, (MoveRequest("allowed-node", "test-library", "group/book"),)
        )
    with pytest.raises(FileMoveError, match="RESOURCE_NOT_FOUND"):
        topology.source("secret-node", actor.library_ids)
    # Layout configuration is part of the frozen source version.
    db_session.get(Library, "test-library").organization_mode = "FLAT"
    db_session.commit()
    assert (
        topology.source("allowed-node", actor.library_ids).revision != source.revision
    )


def test_move_intent_roundtrip_cancellation_and_scope(db_session, tmp_path):
    from dataclasses import replace

    from app.modules.library.application.file_move_operations import (
        move_plan_result,
        move_progress_result,
    )
    from app.modules.library.infrastructure.file_move_operations import (
        SqlAlchemyFileMoveOperations,
    )

    access, root = file_access(db_session, tmp_path)
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    db_session.commit()
    (root / "allowed/file.epub").write_bytes(b"book")
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, (MoveRequest("allowed-node", "test-library", "renamed"),))
    store = SqlAlchemyFileMoveOperations(db_session)
    store.save_plan(plan)
    db_session.commit()
    db_session.expire_all()
    loaded = store.load_plan(plan.id, actor)
    assert loaded == plan
    assert str(root) not in str(move_plan_result(loaded))
    with pytest.raises(FileMoveError, match="RESOURCE_NOT_FOUND"):
        store.load_plan(plan.id, replace(actor, grant_id="another"))
    with pytest.raises(FileMoveError, match="RESOURCE_NOT_FOUND"):
        store.load_plan(plan.id, replace(actor, library_ids=frozenset()))
    assert store.enqueue(loaded, "operation", "request", 2000) == "operation"
    db_session.commit()
    # A second execution key for the same immutable plan cannot queue it twice.
    assert (
        store.enqueue(loaded, "other-operation", "other-request", 3000) == "operation"
    )
    assert store.progress("operation", actor).stages == ("QUEUED",)
    from datetime import UTC, datetime

    from app.contracts.library_file_activity import LibraryFileActivityBusy
    from app.modules.imports.infrastructure.readable_resource.task_queue import (
        SqlAlchemyLibraryImportTaskQueue,
    )

    queue = SqlAlchemyLibraryImportTaskQueue(db_session)
    scan = queue.enqueue(kind="SCAN_LIBRARY", library_id="test-library")
    db_session.commit()
    assert queue.next_queued() is None
    assert store.claim_next(3500) == "operation"
    db_session.rollback()
    with pytest.raises(LibraryFileActivityBusy):
        queue.mark_running(scan.id, started_at=datetime.now(UTC))
    result = store.cancel("operation", actor, 4000)
    db_session.commit()
    assert move_progress_result(result)["cancelled"] == 1
    assert result.status == "CANCELLED"
    assert queue.next_queued().id == scan.id
    assert (root / "allowed/file.epub").read_bytes() == b"book"
    assert not (root / "renamed").exists()
