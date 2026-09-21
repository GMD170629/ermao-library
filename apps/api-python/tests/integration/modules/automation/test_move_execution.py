from datetime import UTC, datetime

import pytest

from app.models import Library, LibraryBook, LibrarySourceNode
from app.modules.imports.infrastructure.readable_resource.task_queue import (
    SqlAlchemyLibraryImportTaskQueue,
)
from app.modules.library.application.execute_file_moves import ExecuteFileMoveOperation
from app.modules.library.application.file_move_plans import (
    MoveActor,
    PrepareFileMovePlan,
)
from app.modules.library.domain.file_moves import FileMoveError, MoveRequest
from app.modules.library.infrastructure.file_move_index import SqlAlchemyFileMoveIndex
from app.modules.library.infrastructure.file_move_io import SameDeviceMovePublication
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.metadata.infrastructure.writeback_queue import (
    discard_relocated_writebacks,
)
from tests.integration.modules.automation.test_file_reads import file_access


def prepare(db, tmp_path):
    access, root = file_access(db, tmp_path)
    db.get(Library, "test-library").organization_mode = "VOLUMES"
    db.commit()
    (root / "allowed/metadata.opf").write_bytes(b"original metadata")
    from dataclasses import replace

    from app.bootstrap.automation import build_automation_settings, build_grant_manager
    from app.modules.automation.application.settings import AutomationServiceSettings
    from app.modules.automation.domain.access import Scope

    permissions = replace(
        access.permissions, scopes=access.permissions.scopes | {Scope.FILES_MOVE}
    )
    grant = build_grant_manager(db).create(
        user_id=access.user_id, name="move", permissions=permissions
    )
    build_automation_settings(db).update(
        access.user_id,
        AutomationServiceSettings(
            enabled=True,
            enabled_scopes=permissions.scopes,
            public_base_url="http://localhost",
        ),
    )
    actor = MoveActor(access.user_id, grant.grant.id, permissions.library_ids, False)
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, (MoveRequest("allowed-node", "test-library", "renamed"),))
    store = SqlAlchemyFileMoveOperations(db)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    assert store.claim_next(3000) == "operation"
    db.commit()
    return actor, root, store


def executor(db, store, files, authorize):
    return ExecuteFileMoveOperation(
        store,
        files,
        SqlAlchemyFileMoveIndex(db),
        authorize,
        SqlAlchemyLibraryImportTaskQueue(db).reconcile_relocation,
        lambda change: discard_relocated_writebacks(db, change),
        db,
        lambda: 4000,
        lambda: datetime.now(UTC),
    )


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_move_publication_and_restart_repair_keep_files_and_identity(
    db_session, tmp_path, crash_after_publish
):
    actor, root, store = prepare(db_session, tmp_path)
    revoked = False

    def authorize(current):
        if revoked:
            raise FileMoveError("AUTHORIZATION_REVOKED")
        return current

    class Files(SameDeviceMovePublication):
        calls = 0

        def validate(self, move):
            assert not db_session.in_transaction()
            super().validate(move)

        def publish(self, move, copy=None):
            assert not db_session.in_transaction()
            super().publish(move, copy)
            self.calls += 1
            if crash_after_publish:
                raise OSError("simulated interruption after rename")

    files = Files()
    command = executor(db_session, store, files, authorize)
    if crash_after_publish:
        with pytest.raises(OSError):
            command.execute("operation")
        assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
        assert (
            db_session.get(LibrarySourceNode, "allowed-node").relative_path == "allowed"
        )
        assert (root / "renamed/metadata.opf").read_bytes() == b"original metadata"
        # A revoked token prevents new targets, but does not forbid completing
        # the exact already-published target's minimum consistency repair.
        revoked = True
        store.prepare_recovery("operation", 5000)
        db_session.commit()
    command.execute("operation")
    assert files.calls == 1
    assert store.progress("operation", actor).status == "COMPLETED"
    assert db_session.get(LibraryBook, "allowed").source_node_id == "allowed-node"
    assert db_session.get(LibrarySourceNode, "allowed-node").relative_path == "renamed"
    assert (root / "renamed/metadata.opf").read_bytes() == b"original metadata"
    assert not (root / "allowed").exists()
    scan = SqlAlchemyLibraryImportTaskQueue(db_session).next_queued()
    assert scan is not None and scan.scan_scopes[0].relative_path == "renamed"


def test_cancel_before_publication_leaves_source_untouched(db_session, tmp_path):
    actor, root, store = prepare(db_session, tmp_path)
    store.cancel("operation", actor, 3500)
    db_session.commit()
    executor(
        db_session, store, SameDeviceMovePublication(), lambda actor: actor
    ).execute("operation")
    assert store.progress("operation", actor).status == "CANCELLED"
    assert (root / "allowed/metadata.opf").read_bytes() == b"original metadata"
    assert not (root / "renamed").exists()


def test_real_grant_revocation_before_publish_prevents_file_and_index_changes(
    db_session, tmp_path
):
    from app.bootstrap.automation import (
        build_automation_authorizer,
        build_grant_manager,
    )
    from app.modules.automation.application.execution import RecheckMoveAccess
    from app.modules.system.infrastructure.automation_settings import (
        SqlAlchemyAutomationSettings,
    )

    actor, root, store = prepare(db_session, tmp_path)

    class RevokeBeforePublish(SameDeviceMovePublication):
        def is_published(self, move, copy=None):
            published = super().is_published(move, copy)
            build_grant_manager(db_session).revoke(
                user_id=actor.user_id, grant_id=actor.grant_id
            )
            return published

    authorize = RecheckMoveAccess(
        build_automation_authorizer(db_session),
        SqlAlchemyAutomationSettings(db_session),
    )
    executor(db_session, store, RevokeBeforePublish(), authorize).execute("operation")
    assert store.progress("operation", actor).status == "FAILED"
    assert (root / "allowed/metadata.opf").read_bytes() == b"original metadata"
    assert not (root / "renamed").exists()
    assert db_session.get(LibrarySourceNode, "allowed-node").relative_path == "allowed"


def test_move_creates_and_indexes_planned_parent_directories(db_session, tmp_path):
    from app.models import LibraryReadableResource
    from tests.integration.modules.automation.test_file_reads import add_file

    access, root = file_access(db_session, tmp_path)
    (root / "allowed").rmdir()
    (root / "allowed").write_bytes(b"publication")
    db_session.get(Library, "test-library").organization_mode = "FLAT"
    node = db_session.get(LibrarySourceNode, "allowed-node")
    node.physical_kind = "REGULAR_FILE"
    node.observed_size_bytes = 11
    db_session.flush()
    db_session.add(
        LibraryReadableResource(
            id="file-resource",
            library_id="test-library",
            book_id="allowed",
            source_node_id="allowed-node",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db_session.commit()
    add_file(db_session, "second-node", "second.epub", parent=None)
    (root / "second.epub").write_bytes(b"second publication")
    db_session.add(
        LibraryBook(
            id="second-book",
            library_id="test-library",
            source_node_id="second-node",
        )
    )
    db_session.flush()
    db_session.add(
        LibraryReadableResource(
            id="second-resource",
            library_id="test-library",
            book_id="second-book",
            source_node_id="second-node",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db_session.commit()
    from app.modules.metadata.application.opf import serialize_opf_metadata
    from app.modules.metadata.public import PublicationMetadata

    (root / "allowed.opf").write_bytes(
        serialize_opf_metadata(
            PublicationMetadata(title="Publication", cover_href="cover.jpg")
        )
    )
    (root / "cover.jpg").write_bytes(b"cover bytes")
    add_file(db_session, "sidecar-node", "allowed.opf", parent=None)
    add_file(db_session, "cover-node", "cover.jpg", parent=None)
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(
        actor,
        (
            MoveRequest("allowed-node", "test-library", "author/series/book.epub"),
            MoveRequest("second-node", "test-library", "author/series/second.epub"),
        ),
    )
    store = SqlAlchemyFileMoveOperations(db_session)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db_session.commit()
    assert store.claim_next(3000) == "operation"
    db_session.commit()
    executor(
        db_session, store, SameDeviceMovePublication(), lambda actor: actor
    ).execute("operation")
    assert store.progress("operation", actor).status == "COMPLETED"
    assert (root / "author/series/book.epub").read_bytes() == b"publication"
    db_session.expire_all()
    moved = db_session.get(LibrarySourceNode, "allowed-node")
    assert moved.relative_path == "author/series/book.epub"
    parent = db_session.get(LibrarySourceNode, moved.parent_id)
    assert parent.relative_path == "author/series"
    assert db_session.get(LibrarySourceNode, parent.parent_id).relative_path == "author"
    assert len(store.execution("operation").created_directories[0]) == 2
    assert (root / "author/series/book.opf").exists()
    assert (root / "author/series/cover.jpg").read_bytes() == b"cover bytes"
    assert not (root / "allowed.opf").exists()
    assert not (root / "cover.jpg").exists()
    assert (
        db_session.get(LibrarySourceNode, "sidecar-node").relative_path
        == "author/series/book.opf"
    )
    assert (
        db_session.get(LibrarySourceNode, "cover-node").relative_path
        == "author/series/cover.jpg"
    )
    assert (root / "author/series/second.epub").read_bytes() == b"second publication"
    assert db_session.get(LibrarySourceNode, "second-node").parent_id == moved.parent_id
    assert store.execution("operation").created_directories[1] == ()


def test_resource_rename_preserves_book_and_rejects_cross_book_move(
    db_session, tmp_path
):
    from app.models import LibraryReadableResource
    from tests.integration.modules.automation.test_file_reads import add_file

    access, root = file_access(db_session, tmp_path)
    db_session.get(Library, "test-library").organization_mode = "VOLUMES"
    add_file(db_session, "volume-node", "allowed/volume.epub")
    (root / "allowed/volume.epub").write_bytes(b"volume")
    db_session.add(
        LibraryReadableResource(
            id="volume",
            library_id="test-library",
            book_id="allowed",
            source_node_id="volume-node",
            adapter_id="epub",
            adapter_version="1",
            format="EPUB",
            enablement_state="ENABLED",
            import_state="READY",
        )
    )
    db_session.commit()
    actor = MoveActor(
        access.user_id, access.grant_id, access.permissions.library_ids, False
    )
    planner = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    )
    with pytest.raises(FileMoveError, match="BOOK_OWNERSHIP_WOULD_CHANGE"):
        planner.execute(
            actor, (MoveRequest("volume-node", "test-library", "other/volume.epub"),)
        )
    plan = planner.execute(
        actor, (MoveRequest("volume-node", "test-library", "allowed/renamed.epub"),)
    )
    assert plan.moves[0].source.complete_book_ids == ()
    store = SqlAlchemyFileMoveOperations(db_session)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db_session.commit()
    assert store.claim_next(3000) == "operation"
    db_session.commit()
    executor(
        db_session, store, SameDeviceMovePublication(), lambda actor: actor
    ).execute("operation")
    assert store.progress("operation", actor).status == "COMPLETED"
    db_session.expire_all()
    assert db_session.get(LibraryBook, "allowed").source_node_id == "allowed-node"
    assert db_session.get(LibraryReadableResource, "volume").book_id == "allowed"
    assert (
        db_session.get(LibrarySourceNode, "volume-node").relative_path
        == "allowed/renamed.epub"
    )
    assert (root / "allowed/renamed.epub").read_bytes() == b"volume"


@pytest.mark.parametrize("interrupt_staging", [False, True])
def test_case_only_directory_rename_recovers_intermediate_slot(
    db_session, tmp_path, monkeypatch, interrupt_staging
):
    from app.modules.library.infrastructure import file_move_io

    actor, root, store = prepare(db_session, tmp_path)
    # Build a second frozen plan with distinct case; discard the unused initial
    # test operation before claiming the replacement.
    from app.modules.library.infrastructure.file_move_schema import (
        LibraryFileMoveOperation,
    )

    db_session.delete(db_session.get(LibraryFileMoveOperation, "operation"))
    db_session.commit()
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "case-plan",
    ).execute(actor, (MoveRequest("allowed-node", "test-library", "Allowed"),))
    assert plan.moves[0].case_only
    store.save_plan(plan)
    store.enqueue(plan, "case-operation", "case-request", 2000)
    db_session.commit()
    assert store.claim_next(3000) == "case-operation"
    db_session.commit()
    rename = file_move_io.exclusive_rename
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        rename(*args)
        if calls == 1 and interrupt_staging:
            raise OSError("interrupted after staging")

    monkeypatch.setattr(file_move_io, "exclusive_rename", interrupted)
    command = executor(
        db_session, store, SameDeviceMovePublication(), lambda actor: actor
    )
    if interrupt_staging:
        with pytest.raises(OSError):
            command.execute("case-operation")
        assert store.progress("case-operation", actor).status == "RECOVERY_REQUIRED"
        assert plan.moves[0].staging_relative_path in [
            entry.name for entry in root.iterdir()
        ]
        store.prepare_recovery("case-operation", 5000)
        db_session.commit()
    command.execute("case-operation")
    assert store.progress("case-operation", actor).status == "COMPLETED"
    assert calls == 2
    assert "Allowed" in [entry.name for entry in root.iterdir()]
    assert "allowed" not in [entry.name for entry in root.iterdir()]
    db_session.expire_all()
    assert db_session.get(LibrarySourceNode, "allowed-node").relative_path == "Allowed"
    assert (root / "Allowed/metadata.opf").read_bytes() == b"original metadata"
