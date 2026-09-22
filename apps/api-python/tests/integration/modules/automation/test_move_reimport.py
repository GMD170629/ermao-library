"""Identity policies and real scan reconciliation for complete volume moves."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from app.bootstrap.readable_resource_pipeline import build_readable_resource_pipeline
from app.contracts.source_relocation import SourceRelocation
from app.models import (
    Library,
    LibraryBook,
    LibraryImportTask,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)
from app.modules.imports.domain.scan_policy import decode_scan_scopes
from app.modules.library.application.file_move_operations import move_plan_result
from app.modules.library.application.file_move_plans import (
    DestinationInspection,
    FileMovePlan,
    MoveActor,
    PlannedMove,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import (
    FileMoveError,
    MoveInventory,
    MoveRequest,
)
from app.modules.library.infrastructure.file_move_index import SqlAlchemyFileMoveIndex
from app.modules.library.infrastructure.file_move_io import SystemMovePublication
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResourceMetadata,
)
from app.modules.reader.infrastructure.persistence.models import (
    ReaderResourceProgressV5,
)
from tests.integration.modules.automation.test_file_reads import (
    add_file,
    file_access,
    opf,
)
from tests.integration.modules.automation.test_move_execution import executor


def volume_fixture(db, tmp_path, *, cross_library=False, directory_format=None):
    access, root = file_access(db, tmp_path)
    library = db.get(Library, "test-library")
    library.organization_mode = "VOLUMES"
    target_library = "private-library" if cross_library else "test-library"
    target_root = tmp_path / "comics" if cross_library else root
    if cross_library:
        target_root.mkdir()
        target = db.get(Library, target_library)
        target.root_path = str(target_root)
        target.organization_mode = "VOLUMES"
    (target_root / "uncle").mkdir()
    db.commit()
    add_file(db, "target-book-node", "uncle", parent=None, kind="DIRECTORY")
    db.get(LibrarySourceNode, "target-book-node").library_id = target_library
    db.flush()
    db.add(
        LibraryBook(
            id="target-book",
            library_id=target_library,
            source_node_id="target-book-node",
        )
    )
    db.commit()
    path = "allowed/13" if directory_format else "allowed/13.txt"
    if directory_format:
        (root / path).mkdir()
    else:
        (root / path).write_text("第十三卷正文", encoding="utf-8")
    add_file(
        db,
        "volume-node",
        path,
        kind="DIRECTORY" if directory_format else "REGULAR_FILE",
    )
    db.add(
        LibraryReadableResource(
            id="volume",
            library_id="test-library",
            book_id="allowed",
            source_node_id="volume-node",
            adapter_id="txt",
            adapter_version="1",
            format=directory_format or "TXT",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db.flush()
    asset_node = "volume-node"
    if directory_format:
        extension = "jpg" if directory_format == "IMAGE_DIR" else "mp3"
        child = path + "/001." + extension
        (root / child).write_bytes(b"original asset")
        add_file(db, "asset-node", child, parent="volume-node")
        asset_node = "asset-node"
    db.add(
        LibraryResourceAsset(
            id="volume-asset",
            library_id="test-library",
            resource_id="volume",
            source_node_id=asset_node,
            source_node_physical_kind="REGULAR_FILE",
            role="PRIMARY",
            import_state="READY",
        )
    )
    db.add(
        LibraryReadableResourceMetadata(
            resource_id="volume",
            title="Manual title",
            protected_fields='["title"]',
        )
    )
    db.add(
        ReaderResourceProgressV5(
            id="volume-progress",
            user_id=access.user_id,
            resource_id="volume",
            client_id="client",
            mutation_id="mutation",
            locator_json='{"href":"old"}',
            presentation_json="{}",
            captured_at=datetime.now(UTC),
            revision=1,
            display_percent=42,
        )
    )
    db.commit()
    # Shared metadata must not prevent moving one complete volume or be taken away.
    (root / "allowed/metadata.opf").write_bytes(opf("Source book"))
    actor = MoveActor(
        access.user_id,
        access.grant_id,
        frozenset({"test-library", target_library}),
        cross_library,
    )
    request = MoveRequest(
        "volume-node",
        target_library,
        "uncle/13" if directory_format else "uncle/13.txt",
    )
    return actor, root, target_root, request


def planner(db):
    return PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    )


def queue_plan(db, actor, request):
    plan = planner(db).execute(actor, (request,))
    store = SqlAlchemyFileMoveOperations(db)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    assert store.claim_next(3000) == "operation"
    db.commit()
    return plan, store


@pytest.mark.parametrize("cross_library", [False, True])
@pytest.mark.parametrize("whole_book", [False, True])
def test_reimport_discards_old_data_and_real_scan_attaches_to_existing_book(
    db_session,
    tmp_path,
    cross_library,
    whole_book,
):
    actor, root, target_root, request = volume_fixture(
        db_session,
        tmp_path,
        cross_library=cross_library,
    )
    # An existing target volume must retain its identity after the incoming scan.
    (target_root / "uncle/12.txt").write_text("Existing volume", encoding="utf-8")
    pipeline = build_readable_resource_pipeline(db_session)
    pipeline.scan_library_source_tree.execute_source("target-book-node")
    existing = db_session.scalar(
        select(LibraryReadableResource.id).where(
            LibraryReadableResource.book_id == "target-book"
        )
    )
    assert existing is not None
    if whole_book:
        request = replace(
            request, node_id="allowed-node", destination_relative_path="uncle/imported"
        )
    plan, store = queue_plan(db_session, actor, request)
    preview = move_plan_result(plan)["moves"][0]
    assert preview["identity_policy"] == "REIMPORT"
    assert preview["discards_identity"] is True
    command = executor(db_session, store, SystemMovePublication(), lambda value: value)
    command.execute("operation")
    assert store.progress("operation", actor).status == "COMPLETED"
    db_session.expire_all()
    assert db_session.get(LibraryReadableResource, "volume") is None
    assert db_session.get(LibraryResourceAsset, "volume-asset") is None
    assert db_session.get(LibraryReadableResourceMetadata, "volume") is None
    assert db_session.get(ReaderResourceProgressV5, "volume-progress") is None
    assert (db_session.get(LibraryBook, "allowed") is None) == whole_book
    if not whole_book:
        assert (root / "allowed/metadata.opf").read_bytes() == opf("Source book")
    assert db_session.get(LibraryReadableResource, existing).book_id == "target-book"
    scans = list(
        db_session.scalars(
            select(LibraryImportTask).where(
                LibraryImportTask.kind == "SCAN_LIBRARY",
                LibraryImportTask.state == "QUEUED",
            )
        )
    )
    assert {task.library_id for task in scans} == {
        "test-library",
        request.destination_library_id,
    }
    for task in scans:
        pipeline.scan_library_source_tree.execute_library(
            task.library_id,
            task_id=task.id,
            scan_scopes=decode_scan_scopes(task.scan_scopes),
        )
    expected_path = "uncle/imported/13.txt" if whole_book else "uncle/13.txt"
    new_resource = db_session.scalar(
        select(LibraryReadableResource)
        .join(
            LibrarySourceNode,
            LibrarySourceNode.id == LibraryReadableResource.source_node_id,
        )
        .where(
            LibrarySourceNode.library_id == request.destination_library_id,
            LibrarySourceNode.relative_path == expected_path,
        )
    )
    assert new_resource is not None
    assert new_resource.id != "volume"
    assert new_resource.book_id == "target-book"
    assert db_session.get(LibraryReadableResource, existing).book_id == "target-book"
    assert (target_root / expected_path).read_text(encoding="utf-8") == "第十三卷正文"


@pytest.mark.parametrize("directory_format", ["IMAGE_DIR", "AUDIOBOOK_DIR"])
def test_complete_directory_resources_reimport_but_individual_assets_are_rejected(
    db_session,
    tmp_path,
    directory_format,
):
    actor, _root, _target_root, request = volume_fixture(
        db_session,
        tmp_path,
        directory_format=directory_format,
    )
    topology = SqlAlchemyMoveTopology(db_session)
    with pytest.raises(FileMoveError, match="COMPLETE_RESOURCE_UNIT_REQUIRED"):
        topology.source("asset-node", actor.library_ids)
    destination = topology.destination(
        topology.source("volume-node", actor.library_ids), request, actor.library_ids
    )
    assert destination.identity_policy == "REIMPORT"


@pytest.mark.parametrize(
    "source_mode,target_mode,whole,target_path,expected",
    [
        ("VOLUMES", "VOLUMES", True, "renamed", "PRESERVE_IDENTITY"),
        ("VOLUMES", "FLAT", True, "renamed", "REIMPORT"),
        ("FLAT", "VOLUMES", True, "uncle/incoming.txt", "REIMPORT"),
        ("FLAT", "FLAT", True, "nested/incoming.txt", "PRESERVE_IDENTITY"),
        ("VOLUMES", "VOLUMES", False, "allowed/renamed.txt", "REIMPORT"),
    ],
)
def test_topology_policy_matrix(
    db_session, tmp_path, source_mode, target_mode, whole, target_path, expected
):
    actor, _root, _target, request = volume_fixture(
        db_session, tmp_path, cross_library=True
    )
    db_session.get(Library, "test-library").organization_mode = source_mode
    db_session.get(Library, "private-library").organization_mode = target_mode
    node_id = "allowed-node" if whole else "volume-node"
    if source_mode == "FLAT":
        db_session.get(LibraryBook, "allowed").source_node_id = "volume-node"
        node_id = "volume-node"
    db_session.commit()
    topology = SqlAlchemyMoveTopology(db_session)
    target = topology.destination(
        topology.source(node_id, actor.library_ids),
        replace(request, node_id=node_id, destination_relative_path=target_path),
        actor.library_ids,
    )
    assert target.identity_policy == expected


@pytest.mark.parametrize("failure_stage", ["publication", "cleanup", "scan_enqueue"])
def test_reimport_failure_never_replays_published_files(
    db_session, tmp_path, failure_stage
):
    actor, root, target_root, request = volume_fixture(db_session, tmp_path)
    _plan, store = queue_plan(db_session, actor, request)
    files = SystemMovePublication()
    command = executor(db_session, store, files, lambda value: value)

    def fail(*_args):
        raise OSError("injected failure")

    if failure_stage == "publication":

        class FailedPublication(SystemMovePublication):
            def publish(self, move):
                fail()

        command = replace(command, files=FailedPublication())
    elif failure_stage == "cleanup":
        command = replace(command, delete_source_node=fail)
    else:
        command = replace(command, reconcile_imports=fail)
    command.execute("operation")
    assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
    assert (root / "allowed/13.txt").exists() == (failure_stage == "publication")
    assert (target_root / "uncle/13.txt").exists() == (failure_stage != "publication")
    db_session.expire_all()
    assert (db_session.get(LibraryReadableResource, "volume") is None) == (
        failure_stage == "scan_enqueue"
    )
    command.execute("operation")
    assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("change", ["mode", "book_identity"])
def test_target_topology_change_requires_new_plan(db_session, tmp_path, change):
    actor, _root, _target, request = volume_fixture(
        db_session, tmp_path, cross_library=True
    )
    move = indexed_move(db_session, actor, request)
    if change == "mode":
        db_session.get(Library, "private-library").organization_mode = "FLAT"
    else:
        book = db_session.get(LibraryBook, "target-book")
        db_session.delete(book)
        db_session.flush()
        db_session.add(
            LibraryBook(
                id="replacement-book",
                library_id="private-library",
                source_node_id="target-book-node",
            )
        )
    db_session.commit()
    with pytest.raises(FileMoveError, match="DESTINATION_CHANGED"):
        SqlAlchemyFileMoveIndex(db_session).validate(move)


def indexed_move(db, actor, request):
    """An already published move for testing index/scan independently of POSIX I/O."""
    topology = SqlAlchemyMoveTopology(db)
    source = topology.source(request.node_id, actor.library_ids)
    destination = topology.destination(source, request, actor.library_ids)
    return PlannedMove(
        source,
        destination,
        MoveInventory((), 0, 0),
        DestinationInspection((), 0, 0, ""),
    )


@pytest.mark.parametrize("whole_book", [False, True])
@pytest.mark.parametrize("directory_format", [None, "IMAGE_DIR", "AUDIOBOOK_DIR"])
def test_published_reimport_cleanup_and_scoped_scan(
    db_session, tmp_path, whole_book, directory_format
):
    actor, root, target_root, request = volume_fixture(
        db_session,
        tmp_path,
        cross_library=True,
        directory_format=directory_format,
    )
    if whole_book:
        request = replace(
            request, node_id="allowed-node", destination_relative_path="uncle/imported"
        )
    (target_root / "uncle/12.txt").write_text("Existing volume", encoding="utf-8")
    pipeline = build_readable_resource_pipeline(db_session)
    pipeline.scan_library_source_tree.execute_source("target-book-node")
    existing_id = db_session.scalar(
        select(LibraryReadableResource.id).where(
            LibraryReadableResource.book_id == "target-book",
        )
    )
    move = indexed_move(db_session, actor, request)
    assert move.destination.identity_policy == "REIMPORT"
    # Publish using the host filesystem here; production system-move coverage is
    # in the end-to-end tests above and requires the POSIX file-access adapter.
    (root / move.source.relative_path).rename(
        target_root / move.destination.relative_path
    )
    index = SqlAlchemyFileMoveIndex(db_session)
    node_ids = index.apply(move, datetime.now(UTC))
    assert pipeline.delete_source_node.execute(move.source.node_id).ok
    pipeline.queue.reconcile_relocation(
        SourceRelocation(
            move.source.library_id,
            move.source.relative_path,
            move.destination.library_id,
            move.destination.relative_path,
            node_ids,
            move.source.book_ids,
            True,
        )
    )
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(LibraryReadableResource, "volume") is None
    assert db_session.get(ReaderResourceProgressV5, "volume-progress") is None
    assert db_session.get(LibraryReadableResourceMetadata, "volume") is None
    assert db_session.get(LibraryResourceAsset, "volume-asset") is None
    assert (db_session.get(LibraryBook, "allowed") is None) == whole_book
    source_scan = db_session.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.library_id == "test-library",
            LibraryImportTask.kind == "SCAN_LIBRARY",
        )
    )
    pipeline.scan_library_source_tree.execute_library(
        source_scan.library_id,
        task_id=source_scan.id,
        scan_scopes=decode_scan_scopes(source_scan.scan_scopes),
    )
    task = db_session.scalar(
        select(LibraryImportTask).where(
            LibraryImportTask.library_id == "private-library",
            LibraryImportTask.kind == "SCAN_LIBRARY",
        )
    )
    pipeline.scan_library_source_tree.execute_library(
        task.library_id,
        task_id=task.id,
        scan_scopes=decode_scan_scopes(task.scan_scopes),
    )
    resources = list(
        db_session.scalars(
            select(LibraryReadableResource).where(
                LibraryReadableResource.book_id == "target-book",
            )
        )
    )
    assert len(resources) == 2
    assert db_session.get(LibraryReadableResource, existing_id).book_id == "target-book"
    incoming = next(resource for resource in resources if resource.id != existing_id)
    assert incoming.id != "volume"
    assert incoming.format == (directory_format or "TXT")


@pytest.mark.parametrize("failure_stage", [None, "cleanup", "scan_enqueue"])
def test_executor_reconciles_published_reimport_without_replaying_files(
    db_session,
    tmp_path,
    failure_stage,
):
    actor, root, target_root, request = volume_fixture(db_session, tmp_path)
    move = indexed_move(db_session, actor, request)
    plan = FileMovePlan("plan", actor, 1000, 999999, (move,), execution_version=3)
    store = SqlAlchemyFileMoveOperations(db_session)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db_session.commit()
    assert store.claim_next(3000) == "operation"
    db_session.commit()
    (root / move.source.relative_path).rename(
        target_root / move.destination.relative_path
    )
    store.checkpoint("operation", 0, "FILES_PUBLISHED", 3500)
    db_session.commit()
    files = Mock(spec=SystemMovePublication)
    files.is_published.return_value = True
    command = executor(db_session, store, files, lambda value: value)
    if failure_stage:

        def fail(*_args):
            raise OSError("injected reconciliation failure")

        command = replace(
            command,
            **{
                "delete_source_node"
                if failure_stage == "cleanup"
                else "reconcile_imports": fail,
            },
        )
    command.execute("operation")
    expected = "RECOVERY_REQUIRED" if failure_stage else "COMPLETED"
    assert store.progress("operation", actor).status == expected
    db_session.expire_all()
    assert (db_session.get(LibraryReadableResource, "volume") is None) == (
        failure_stage != "cleanup"
    )
    command.execute("operation")
    files.publish.assert_not_called()
    assert (target_root / "uncle/13.txt").read_text(encoding="utf-8") == "第十三卷正文"


@pytest.mark.parametrize("cross_library", [False, True])
def test_published_whole_book_preserves_metadata_progress_and_ids(
    db_session, tmp_path, cross_library
):
    actor, root, target_root, request = volume_fixture(
        db_session, tmp_path, cross_library=cross_library
    )
    request = replace(
        request, node_id="allowed-node", destination_relative_path="renamed"
    )
    move = indexed_move(db_session, actor, request)
    assert move.destination.identity_policy == "PRESERVE_IDENTITY"
    (root / "allowed").rename(target_root / "renamed")
    SqlAlchemyFileMoveIndex(db_session).apply(move, datetime.now(UTC))
    db_session.commit()
    db_session.expire_all()
    assert (
        db_session.get(LibraryBook, "allowed").library_id
        == request.destination_library_id
    )
    assert db_session.get(LibraryReadableResource, "volume").book_id == "allowed"
    assert db_session.get(LibraryResourceAsset, "volume-asset").resource_id == "volume"
    assert (
        db_session.get(LibraryReadableResourceMetadata, "volume").title
        == "Manual title"
    )
    assert (
        db_session.get(ReaderResourceProgressV5, "volume-progress").display_percent
        == 42
    )
    assert (
        db_session.get(LibrarySourceNode, "volume-node").relative_path
        == "renamed/13.txt"
    )
