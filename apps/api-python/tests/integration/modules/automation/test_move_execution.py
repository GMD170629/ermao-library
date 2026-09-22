import logging
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.failure_diagnostics import RuntimeFailureDiagnostics
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
from app.modules.library.infrastructure.file_move_io import SystemMovePublication
from app.modules.library.infrastructure.file_move_operations import (
    SqlAlchemyFileMoveOperations,
)
from app.modules.library.infrastructure.move_inventory import AnchoredMoveInspection
from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
from app.modules.metadata.infrastructure.writeback_queue import (
    discard_relocated_writebacks,
)
from tests.integration.modules.automation.test_file_reads import file_access


def prepare(db, tmp_path, *, dynamic=False, batch=False):
    access, root = file_access(db, tmp_path)
    db.get(Library, "test-library").organization_mode = "VOLUMES"
    db.commit()
    (root / "allowed/metadata.opf").write_bytes(b"original metadata")
    from dataclasses import replace

    from app.bootstrap.automation import build_automation_settings, build_grant_manager
    from app.modules.automation.application.settings import AutomationServiceSettings
    from app.modules.automation.domain.access import Scope

    permissions = replace(
        access.permissions, scopes=access.permissions.scopes | {Scope.FILES_MODIFY}
    )
    build_automation_settings(db).update(
        access.user_id,
        AutomationServiceSettings(
            enabled=True,
            enabled_scopes=permissions.scopes,
            public_base_url="http://localhost",
        ),
    )
    grant = build_grant_manager(db).create(
        user_id=access.user_id,
        name="move",
        permissions=replace(permissions, library_scope="all", library_ids=frozenset())
        if dynamic
        else permissions,
    )

    actor = MoveActor(access.user_id, grant.grant.id, permissions.library_ids, False)
    requests = [MoveRequest("allowed-node", "test-library", "renamed")]
    if batch:
        from tests.integration.modules.automation.test_file_reads import add_file

        for name in ("second", "third"):
            (root / name).mkdir()
            (root / name / "book.txt").write_text(name)
            add_file(db, name + "-node", name, parent=None, kind="DIRECTORY")
            db.add(
                LibraryBook(
                    id=name, library_id="test-library", source_node_id=name + "-node"
                )
            )
            db.commit()
            requests.append(
                MoveRequest(name + "-node", "test-library", name + "-moved")
            )
    plan = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db),
        AnchoredMoveInspection(),
        lambda: 1000,
        lambda: "plan",
    ).execute(actor, tuple(requests))
    store = SqlAlchemyFileMoveOperations(db)
    store.save_plan(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    assert store.claim_next(3000) == "operation"
    db.commit()
    return actor, root, store


def failure_diagnostics(db):
    return RuntimeFailureDiagnostics(
        logging.getLogger(__name__), "library", lambda: Session(db.get_bind())
    )


def executor(db, store, files, authorize):
    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
    )
    from app.modules.imports.infrastructure.readable_resource.source_node_deletion import (
        LibrarySourceNodeDeletionAdapter,
    )

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
        diagnostics=failure_diagnostics(db),
        delete_source_node=LibrarySourceNodeDeletionAdapter(
            build_readable_resource_pipeline(db).delete_source_node
        ).delete_source_node,
    )


@pytest.mark.parametrize("crash_after_publish", [False, True])
def test_move_publication_and_interruption_keep_files_and_identity(
    db_session, tmp_path, crash_after_publish
):
    actor, root, store = prepare(db_session, tmp_path)
    revoked = False

    def authorize(current):
        if revoked:
            raise FileMoveError("AUTHORIZATION_REVOKED")
        return current

    class Files(SystemMovePublication):
        calls = 0

        def validate(self, move):
            assert not db_session.in_transaction()
            super().validate(move)

        def publish(self, move):
            assert not db_session.in_transaction()
            super().publish(move)
            self.calls += 1
            if crash_after_publish:
                raise OSError("simulated interruption after rename")

    files = Files()
    command = executor(db_session, store, files, authorize)
    if crash_after_publish:
        command.execute("operation")
        assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
        assert (
            db_session.get(LibrarySourceNode, "allowed-node").relative_path == "allowed"
        )
        assert (root / "renamed/metadata.opf").read_bytes() == b"original metadata"
        revoked = True
        store.prepare_recovery("operation", 5000)
        db_session.commit()
        command.execute("operation")
        assert store.progress("operation", actor).status == "RECOVERY_REQUIRED"
        assert files.calls == 1
        assert (
            db_session.get(LibrarySourceNode, "allowed-node").relative_path == "allowed"
        )
        return
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
    executor(db_session, store, SystemMovePublication(), lambda actor: actor).execute(
        "operation"
    )
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

    class RevokeBeforePublish(SystemMovePublication):
        def is_published(self, move):
            published = super().is_published(move)
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
    executor(db_session, store, SystemMovePublication(), lambda actor: actor).execute(
        "operation"
    )
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


def test_resource_rename_preserves_parent_book_and_discards_resource_identity(
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
    other_plan = planner.execute(
        actor, (MoveRequest("volume-node", "test-library", "other/volume.epub"),)
    )
    assert other_plan.moves[0].destination.identity_policy == "REIMPORT"
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
    executor(db_session, store, SystemMovePublication(), lambda actor: actor).execute(
        "operation"
    )
    assert store.progress("operation", actor).status == "COMPLETED"
    db_session.expire_all()
    assert db_session.get(LibraryBook, "allowed").source_node_id == "allowed-node"
    assert db_session.get(LibraryReadableResource, "volume") is None
    assert db_session.get(LibrarySourceNode, "volume-node") is None
    assert (root / "allowed/renamed.epub").read_bytes() == b"volume"


@pytest.mark.parametrize("interrupt_rename", [False, True])
def test_case_only_directory_rename_uses_native_rename_without_staging(
    db_session, tmp_path, monkeypatch, interrupt_rename
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
    rename = file_move_io.os.rename
    calls = 0

    def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        rename(*args, **kwargs)
        if calls == 1 and interrupt_rename:
            raise OSError("interrupted after staging")

    monkeypatch.setattr(file_move_io.os, "rename", interrupted)
    command = executor(db_session, store, SystemMovePublication(), lambda actor: actor)
    if interrupt_rename:
        command.execute("case-operation")
        assert store.progress("case-operation", actor).status == "RECOVERY_REQUIRED"
        assert (root / "Allowed/metadata.opf").read_bytes() == b"original metadata"
        assert not any(path.name.startswith(".ermao-mcp-") for path in root.iterdir())
        store.prepare_recovery("case-operation", 5000)
        db_session.commit()
        command.execute("case-operation")
        assert store.progress("case-operation", actor).status == "RECOVERY_REQUIRED"
        assert calls == 1
        return
    command.execute("case-operation")
    assert store.progress("case-operation", actor).status == "COMPLETED"
    assert calls == 1
    assert "Allowed" in [entry.name for entry in root.iterdir()]
    assert "allowed" not in [entry.name for entry in root.iterdir()]
    db_session.expire_all()
    assert db_session.get(LibrarySourceNode, "allowed-node").relative_path == "Allowed"
    assert (root / "Allowed/metadata.opf").read_bytes() == b"original metadata"


@pytest.mark.parametrize("withdraw_access", [False, True])
def test_dynamic_grant_rechecks_worker_and_history_without_expanding_frozen_plan(
    client, db_session, tmp_path, withdraw_access
):
    from app.bootstrap.automation import build_automation_authorizer
    from app.models.auth import User, UserLibraryAccess
    from app.modules.automation.application.execution import RecheckMoveAccess
    from app.modules.system.infrastructure.automation_settings import (
        SqlAlchemyAutomationSettings,
    )
    from tests.integration.modules.automation.test_operation_management import cookie

    actor, root, store = prepare(db_session, tmp_path, dynamic=True)
    user = db_session.get(User, actor.user_id)
    user.role = "member"
    user.can_manage_system = True
    db_session.add(UserLibraryAccess(user_id=actor.user_id, library_id="test-library"))
    new_root = tmp_path / "new-library"
    new_root.mkdir()
    (new_root / "untouched.txt").write_text("untouched")
    db_session.add(
        Library(
            id="new-dynamic-library",
            name="New",
            root_path=str(new_root),
            organization_mode="FLAT",
        )
    )
    db_session.flush()
    db_session.add(
        UserLibraryAccess(user_id=actor.user_id, library_id="new-dynamic-library")
    )
    db_session.commit()
    cookie(client, db_session)
    authorizer = RecheckMoveAccess(
        build_automation_authorizer(db_session),
        SqlAlchemyAutomationSettings(db_session),
    )
    assert authorizer(actor).library_ids == frozenset(
        {"test-library", "new-dynamic-library"}
    )
    visible = client.get("/api/automation/operations").json()["data"]["operations"]
    assert len(visible) == 1 and visible[0]["total_targets"] == 1
    if withdraw_access:
        db_session.delete(
            db_session.scalar(
                select(UserLibraryAccess).where(
                    UserLibraryAccess.user_id == actor.user_id,
                    UserLibraryAccess.library_id == "test-library",
                )
            )
        )
        db_session.commit()
        assert (
            client.get("/api/automation/operations").json()["data"]["operations"] == []
        )
    executor(db_session, store, SystemMovePublication(), authorizer).execute(
        "operation"
    )
    assert store.progress("operation", actor).status == (
        "FAILED" if withdraw_access else "COMPLETED"
    )
    assert (new_root / "untouched.txt").read_text() == "untouched"
    assert (
        root / ("allowed" if withdraw_access else "renamed") / "metadata.opf"
    ).read_bytes() == b"original metadata"


@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize("failure", ["validation", "publication", "unexpected"])
def test_move_batch_isolates_failed_targets(
    client, db_session, tmp_path, failure_index, failure
):
    actor, root, store = prepare(db_session, tmp_path, batch=True)
    plan = store.execution("operation").plan
    failing = plan.moves[failure_index].source.relative_path

    class Files(SystemMovePublication):
        def validate(self, move):
            if failure == "validation" and move.source.relative_path == failing:
                raise FileMoveError("SOURCE_CHANGED")
            super().validate(move)

        def publish(self, move):
            if move.source.relative_path == failing:
                if failure == "publication":
                    raise FileMoveError("DESTINATION_COLLISION")
                if failure == "unexpected":
                    raise OSError("unavailable target")
            super().publish(move)

    executor(db_session, store, Files(), lambda actor: actor).execute("operation")
    expected = ["COMPLETED"] * 3
    expected[failure_index] = (
        "FAILED" if failure == "validation" else "RECOVERY_REQUIRED"
    )
    assert store.progress("operation", actor).stages == tuple(expected)
    for index, move in enumerate(plan.moves):
        assert (root / move.destination.relative_path).exists() == (
            index != failure_index
        )
        assert (root / move.source.relative_path).exists() == (index == failure_index)
    from tests.integration.modules.automation.test_operation_management import cookie

    cookie(client, db_session)
    response = client.get("/api/automation/operations")
    assert response.status_code == 200
    operation = next(
        item
        for item in response.json()["data"]["operations"]
        if item["operation_id"] == "operation"
    )
    assert [item["stage"] for item in operation["targets"]] == expected


@pytest.mark.parametrize("interrupted", [False, True])
def test_restart_claims_queued_siblings_without_replaying_failed_move(
    db_session, tmp_path, interrupted, caplog
):
    from app.modules.library.application.file_move_worker import FileMoveWorker
    from app.modules.library.infrastructure.file_move_schema import (
        LibraryFileMoveOperation,
    )

    actor, root, store = prepare(db_session, tmp_path, batch=True)
    store.checkpoint(
        "operation",
        0,
        "PREPARING" if interrupted else "RECOVERY_REQUIRED",
        3500,
        None if interrupted else "COPY_ATTRIBUTES_NOT_PRESERVED",
    )
    if not interrupted:
        store.finish("operation", 3500)
    db_session.commit()
    files = SystemMovePublication()
    restarted = SqlAlchemyFileMoveOperations(db_session)
    worker = FileMoveWorker(
        restarted,
        executor(db_session, restarted, files, lambda actor: actor),
        db_session,
        lambda: 4000,
        diagnostics=failure_diagnostics(db_session),
    )
    if interrupted:
        assert worker.process_once()  # Quarantine interrupted target before new claims.
        from app.models import SystemEvent

        event = db_session.scalar(
            select(SystemEvent).where(
                SystemEvent.action == "file_move.previous_result_unavailable"
            )
        )
        assert event is not None
        assert event.metadata_json["operationId"] == "operation"
        assert event.metadata_json["targetOrdinal"] == 0
        assert event.metadata_json["stage"] == "PREPARING"
        assert event.metadata_json["step"] == "inspect_recovery_state"
        assert event.metadata_json["diagnostics"]["causeStatus"] == "NOT_PROVIDED"
        assert "previous move result was not provided" in caplog.text
        assert (
            db_session.get(LibraryFileMoveOperation, "operation").status
            == "RECOVERY_REQUIRED"
        )
    assert worker.process_once()
    assert restarted.progress("operation", actor).stages == (
        "RECOVERY_REQUIRED",
        "COMPLETED",
        "COMPLETED",
    )
    assert (root / "allowed/metadata.opf").read_bytes() == b"original metadata"
    assert not (root / "renamed").exists()
    assert (root / "second-moved/book.txt").read_text() == "second"
    assert restarted.claim_next(5000) is None


@pytest.mark.parametrize("cancel", [False, True])
def test_recovery_move_does_not_block_new_same_source_task(
    db_session, tmp_path, cancel
):
    actor, root, store = prepare(db_session, tmp_path, batch=True)
    store.checkpoint(
        "operation", 0, "RECOVERY_REQUIRED", 3500, "COPY_ATTRIBUTES_NOT_PRESERVED"
    )
    store.finish("operation", 3500)
    db_session.commit()
    if cancel:
        store.cancel("operation", actor, 3600)
        db_session.commit()
    assert store.claim_next(4000) == "operation"
    db_session.commit()
    assert store.claim_next(4000) is None  # Already owned; not claimed twice.
    db_session.rollback()
    executor(db_session, store, SystemMovePublication(), lambda actor: actor).execute(
        "operation"
    )
    sibling = "CANCELLED" if cancel else "COMPLETED"
    assert store.progress("operation", actor).stages == (
        "RECOVERY_REQUIRED",
        sibling,
        sibling,
    )
    fresh = PrepareFileMovePlan(
        SqlAlchemyMoveTopology(db_session),
        AnchoredMoveInspection(),
        lambda: 5000,
        lambda: "fresh-plan",
    ).execute(
        actor, (MoveRequest("allowed-node", "test-library", "fresh-destination"),)
    )
    store.save_plan(fresh)
    store.enqueue(fresh, "fresh", "fresh-request", 6000)
    db_session.commit()
    assert store.claim_next(7000) == "fresh"
    db_session.commit()
    executor(db_session, store, SystemMovePublication(), lambda actor: actor).execute(
        "fresh"
    )
    assert store.progress("fresh", actor).status == "COMPLETED"
    assert (
        root / "fresh-destination/metadata.opf"
    ).read_bytes() == b"original metadata"
    assert store.progress("operation", actor).stages[0] == "RECOVERY_REQUIRED"


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("started", [False, True])
def test_legacy_move_plan_never_replays_files_or_cleans_backup(
    db_session, tmp_path, started, version
):
    from app.modules.library.infrastructure.file_move_schema import LibraryFileMovePlan

    actor, root, store = prepare(db_session, tmp_path)
    row = db_session.get(LibraryFileMovePlan, "plan")
    payload = dict(row.payload)
    payload["execution_version"] = version
    payload["moves"][0]["staging_relative_path"] = ".ermao-mcp-legacy-target"
    payload["moves"][0]["backup_relative_path"] = ".ermao-mcp-legacy-source"
    row.payload = payload
    backup = root / ".ermao-mcp-legacy-source"
    backup.write_bytes(b"legacy recovery content")
    if started:
        store.checkpoint("operation", 0, "PREPARING", 3500)
    db_session.commit()
    files = SystemMovePublication()
    command = executor(db_session, store, files, lambda value: value)
    command.execute("operation")
    progress = store.progress("operation", actor)
    assert progress.status == ("RECOVERY_REQUIRED" if started else "FAILED")
    assert progress.error_codes == ("MOVE_PLAN_REQUIRES_REFRESH",)
    command.execute("operation")
    assert (root / "allowed/metadata.opf").read_bytes() == b"original metadata"
    assert not (root / "renamed").exists()
    assert backup.read_bytes() == b"legacy recovery content"
    assert not hasattr(files, "clear_backup")


@pytest.mark.parametrize("version", [1, 2])
def test_old_preview_requires_refresh_before_new_enqueue(db_session, tmp_path, version):
    from dataclasses import replace

    actor, root, store = prepare(db_session, tmp_path)
    legacy = replace(
        store.load_plan("plan", actor), id="old-preview", execution_version=version
    )
    store.save_plan(legacy)
    db_session.commit()
    with pytest.raises(FileMoveError, match="MOVE_PLAN_REQUIRES_REFRESH"):
        store.enqueue(legacy, "never-enqueued", "legacy-request", 4000)
    db_session.rollback()
    assert store.load_plan("old-preview", actor).execution_version == version
    assert (root / "allowed").is_dir()
