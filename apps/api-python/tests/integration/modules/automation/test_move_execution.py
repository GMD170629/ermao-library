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

        def publish(self, move):
            assert not db_session.in_transaction()
            super().publish(move)
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
