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


def test_same_disk_cross_library_move_keeps_book_resource_asset_and_shelf_ids(
    db_session, tmp_path
):
    from datetime import UTC, datetime

    from app.models import (
        LibraryBook,
        LibraryReadableResource,
        LibraryResourceAsset,
        LibrarySourceNode,
    )
    from app.models.shelf import ShelfBook
    from app.modules.library.infrastructure.file_move_index import (
        SqlAlchemyFileMoveIndex,
    )
    from app.modules.library.infrastructure.file_move_io import publish_same_device_move
    from tests.integration.modules.automation.test_file_reads import add_file

    access, root = file_access(db_session, tmp_path)
    destination_root = tmp_path / "destination"
    destination_root.mkdir()
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    destination = db_session.get(Library, "private-library")
    destination.organization_mode = "VOLUMES"
    destination.root_path = str(destination_root)
    db_session.commit()
    (root / "allowed/book.epub").write_bytes(b"book bytes")
    add_file(db_session, "resource-node", "allowed/book.epub")
    db_session.add(
        LibraryReadableResource(
            id="move-resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="resource-node",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryResourceAsset(
            id="move-asset",
            library_id="test-library",
            resource_id="move-resource",
            source_node_id="resource-node",
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db_session.commit()
    actor = MoveActor(
        access.user_id,
        access.grant_id,
        frozenset({"test-library", "private-library"}),
        True,
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, (MoveRequest("allowed-node", "private-library", "renamed"),))
    db_session.rollback()
    publish_same_device_move(plan.moves[0])
    ids = SqlAlchemyFileMoveIndex(db_session).apply(plan.moves[0], datetime.now(UTC))
    db_session.commit()
    db_session.expire_all()
    assert set(ids) == {"allowed-node", "resource-node"}
    assert db_session.get(LibraryBook, "allowed").library_id == "private-library"
    assert (
        db_session.get(LibraryReadableResource, "move-resource").library_id
        == "private-library"
    )
    assert (
        db_session.get(LibraryResourceAsset, "move-asset").library_id
        == "private-library"
    )
    assert (
        db_session.get(LibrarySourceNode, "resource-node").relative_path
        == "renamed/book.epub"
    )
    assert (
        db_session.get(LibrarySourceNode, "resource-node").parent_id == "allowed-node"
    )
    assert (
        db_session.get(ShelfBook, {"shelf_id": "static", "book_id": "allowed"})
        is not None
    )
    assert (destination_root / "renamed/book.epub").read_bytes() == b"book bytes"
    assert not (root / "allowed").exists()


def test_cross_device_recovery_quota_is_reserved_before_queueing(db_session, tmp_path):
    from dataclasses import replace

    from app.modules.library.infrastructure.file_move_operations import (
        SqlAlchemyFileMoveOperations,
    )

    access, root = file_access(db_session, tmp_path)
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    db_session.commit()
    (root / "allowed/book").write_bytes(b"1234567890")
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "first",
    ).execute(actor, (MoveRequest("allowed-node", "test-library", "renamed"),))
    move = plan.moves[0]
    # Only admission arithmetic is under test; actual cross-device I/O is covered
    # using a separately mounted filesystem in test_cross_device_moves.py.
    plan = replace(
        plan,
        moves=(
            replace(
                move,
                destination_inspection=replace(
                    move.destination_inspection,
                    device=move.inventory.entries[0].identity.device + 1,
                ),
            ),
        ),
    )
    second = replace(plan, id="second")
    store = SqlAlchemyFileMoveOperations(db_session, recovery_byte_limit=15)
    store.save_plan(plan)
    store.save_plan(second)
    store.enqueue(plan, "operation", "first-key", 2000)
    db_session.commit()
    with pytest.raises(FileMoveError, match="RECOVERY_QUOTA_EXCEEDED"):
        store.enqueue(second, "second-operation", "second-key", 2000)
    db_session.rollback()
    store.cancel("operation", actor, 3000)
    db_session.commit()
    assert (
        store.enqueue(second, "second-operation", "second-key", 3000)
        == "second-operation"
    )
    db_session.rollback()
    assert (root / "allowed/book").read_bytes() == b"1234567890"
