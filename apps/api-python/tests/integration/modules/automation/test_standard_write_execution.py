from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models.organize import MetadataWritebackTarget
from app.modules.automation.application.writeback_plans import StandardWriteSelection
from app.modules.library.infrastructure.standard_writeback_index import (
    SqlAlchemyStandardWriteIndex,
)
from app.modules.metadata.application.execute_standard_writeback import (
    ExecuteStandardWrite,
)
from app.modules.metadata.infrastructure.standard_writeback_schema import (
    MetadataStandardWriteTarget,
)
from app.modules.metadata.infrastructure.standard_writeback_store import (
    SqlAlchemyStandardWritePlans,
)
from app.services.metadata_file_writeback import process_next_metadata_writeback
from tests.integration.modules.automation.test_move_execution import failure_diagnostics
from tests.integration.modules.automation.test_writeback_plans import opf, setup


def prepared(db, tmp_path, *, batch=False):
    access, root, catalog, planner = setup(db, tmp_path)
    if batch:
        from app.bootstrap.automation import build_grant_manager

        grant = build_grant_manager(db).create(
            user_id=access.user_id, name="batch writer", permissions=access.permissions
        )
        access = replace(access, grant_id=grant.grant.id)
    original = opf("Before")
    (root / "allowed/metadata.opf").write_bytes(original)
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    plan = planner.execute(
        access,
        (
            StandardWriteSelection(
                "book",
                "allowed",
                schema["expected_revision"],
                "allowed-node",
                "opf",
                frozenset({"title"}),
            ),
        ),
    )
    if batch:
        target = plan.targets[0]
        siblings = tuple(
            replace(
                target,
                file=replace(
                    target.file,
                    relative_path=f"allowed/{name}.opf",
                    original=None,
                    prepared_name=f".ermao-mcp-{index:032x}-target",
                    backup_name=f".ermao-mcp-{index:032x}-source",
                ),
            )
            for index, name in enumerate(("second", "third"), 1)
        )
        plan = replace(plan, targets=(*plan.targets, *siblings))
    store = SqlAlchemyStandardWritePlans(db, queue_capacity=20)
    store.save(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db.commit()
    return root, original, planner.files, store, plan


def test_existing_worker_queue_publishes_standard_file_and_records_result(
    db_session, tmp_path
):
    root, original, files, store, plan = prepared(db_session, tmp_path)
    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )

    def handler(db, target, owner):
        payload = target["payload"]
        executor.execute(payload["standard_operation_id"], payload["ordinal"], owner)

    assert process_next_metadata_writeback(
        db_session, Settings(), standard_handler=handler
    )
    target = db_session.get(MetadataStandardWriteTarget, ("operation", 0))
    assert target.stage == "COMPLETED"
    assert not target.recovery_released
    assert (
        root / "allowed" / plan.targets[0].file.backup_name
    ).read_bytes() == original
    assert (root / "allowed/metadata.opf").read_bytes() != original
    assert (
        db_session.scalar(select(func.count()).select_from(MetadataWritebackTarget))
        == 0
    )


def test_interruption_after_publication_retains_result_without_replay(
    db_session, tmp_path
):
    root, original, files, store, plan = prepared(db_session, tmp_path)

    def interrupted(*_):
        raise RuntimeError("simulated process failure before index commit")

    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        interrupted,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )

    def handler(db, target, owner):
        executor.execute("operation", 0, owner)

    assert process_next_metadata_writeback(
        db_session, Settings(), standard_handler=handler
    )
    target = db_session.get(MetadataStandardWriteTarget, ("operation", 0))
    assert target.stage == "RECOVERY_REQUIRED"
    published_inode = (root / "allowed/metadata.opf").stat().st_ino

    # Restart never requeues REVIEW entries; their evidence remains available.
    from app.services.metadata_file_writeback import (
        recover_interrupted_metadata_writebacks,
    )

    assert recover_interrupted_metadata_writebacks(db_session) == 0
    assert not process_next_metadata_writeback(
        db_session, Settings(), owner_id="restarted-worker", standard_handler=handler
    )
    assert (
        db_session.get(MetadataStandardWriteTarget, ("operation", 0)).stage
        == "RECOVERY_REQUIRED"
    )
    assert (root / "allowed/metadata.opf").stat().st_ino == published_inode
    assert (
        root / "allowed" / plan.targets[0].file.backup_name
    ).read_bytes() == original


def test_expired_backup_requires_unchanged_published_file(db_session, tmp_path):
    root, original, files, store, plan = prepared(db_session, tmp_path)
    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )
    assert process_next_metadata_writeback(
        db_session,
        Settings(),
        standard_handler=lambda db, target, owner: executor.execute(
            "operation", 0, owner
        ),
    )
    assert store.expired_backups(4000) == ()
    entries = store.expired_backups(3000 + 2 * 24 * 60 * 60_000)
    assert len(entries) == 1
    _, _, _, proof = entries[0]
    db_session.rollback()
    backup = root / "allowed" / plan.targets[0].file.backup_name
    published = root / "allowed/metadata.opf"
    published.write_bytes(b"user changed file after writeback")
    import pytest

    from app.modules.metadata.public import StandardMetadataError

    with pytest.raises(StandardMetadataError):
        files.clear_backup(plan.targets[0].file, proof)
    assert backup.read_bytes() == original


def test_successful_backup_cleanup_releases_shared_reservation(db_session, tmp_path):
    from app.infrastructure.file_recovery_budget import reserved_file_recovery_bytes

    root, _, files, store, plan = prepared(db_session, tmp_path)
    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )
    assert process_next_metadata_writeback(
        db_session,
        Settings(),
        standard_handler=lambda db, target, owner: executor.execute(
            "operation", 0, owner
        ),
    )
    assert reserved_file_recovery_bytes(db_session) > 0
    now = 3000 + 2 * 24 * 60 * 60_000
    _, _, _, proof = store.expired_backups(now)[0]
    db_session.rollback()
    files.clear_backup(plan.targets[0].file, proof)
    store.backup_cleanup_result("operation", 0, now, failed=False)
    db_session.commit()
    assert reserved_file_recovery_bytes(db_session) == 0
    assert not (root / "allowed" / plan.targets[0].file.backup_name).exists()


def test_worker_checks_real_grant_revocation_before_any_file_change(
    db_session, tmp_path
):
    from dataclasses import replace

    from app.bootstrap.automation import build_automation_settings, build_grant_manager
    from app.bootstrap.standard_writeback import process_standard_writeback
    from app.modules.automation.application.settings import AutomationServiceSettings

    access, root, catalog, planner = setup(db_session, tmp_path)
    grant = build_grant_manager(db_session).create(
        user_id=access.user_id, name="writer", permissions=access.permissions
    )
    access = replace(access, grant_id=grant.grant.id)
    build_automation_settings(db_session).update(
        access.user_id,
        AutomationServiceSettings(
            enabled=True,
            enabled_scopes=access.permissions.scopes,
            public_base_url="http://localhost",
        ),
    )
    schema = catalog.get_metadata_schema(access, "book", "allowed")
    plan = planner.execute(
        access,
        (
            StandardWriteSelection(
                "book",
                "allowed",
                schema["expected_revision"],
                "allowed-node",
                "opf",
                frozenset({"title"}),
            ),
        ),
    )
    store = SqlAlchemyStandardWritePlans(db_session, queue_capacity=20)
    store.save(plan)
    store.enqueue(plan, "operation", "request", 2000)
    db_session.commit()
    build_grant_manager(db_session).revoke(
        user_id=access.user_id, grant_id=grant.grant.id
    )
    assert process_next_metadata_writeback(
        db_session, Settings(), standard_handler=process_standard_writeback
    )
    target = db_session.get(MetadataStandardWriteTarget, ("operation", 0))
    assert target.stage == "FAILED"
    assert target.error_code == "AUTHORIZATION_REVOKED"
    assert list((root / "allowed").iterdir()) == []


def test_standard_write_and_scan_claims_exclude_each_other(db_session, tmp_path):
    from datetime import UTC, datetime

    from app.modules.imports.infrastructure.readable_resource.task_queue import (
        SqlAlchemyLibraryImportTaskQueue,
    )
    from app.modules.metadata.infrastructure.writeback_queue import claim_next_target

    _, _, _, _, _ = prepared(db_session, tmp_path)
    scans = SqlAlchemyLibraryImportTaskQueue(db_session)
    task = scans.enqueue(kind="SCAN_LIBRARY", library_id="test-library")
    scans.mark_running(task.id, started_at=datetime.now(UTC))
    db_session.commit()
    assert (
        claim_next_target(db_session, owner_id="worker", now=datetime.now(UTC)) is None
    )
    scans.mark_succeeded(task.id, finished_at=datetime.now(UTC))
    db_session.commit()
    claimed = claim_next_target(db_session, owner_id="worker", now=datetime.now(UTC))
    assert claimed is not None
    db_session.commit()
    scans.enqueue(kind="SCAN_LIBRARY", library_id="test-library")
    db_session.commit()
    assert scans.next_queued() is None
    # A retained uncertain result does not own an execution slot.
    queue = db_session.get(MetadataWritebackTarget, claimed["id"])
    queue.status = "REVIEW"
    db_session.commit()
    ready = scans.next_queued()
    assert ready is not None
    scans.mark_running(ready.id, started_at=datetime.now(UTC))
    db_session.commit()


def test_completed_writeback_backup_does_not_hold_locator(db_session, tmp_path):
    from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology

    root, original, files, store, plan = prepared(db_session, tmp_path)
    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )
    assert process_next_metadata_writeback(
        db_session,
        Settings(),
        standard_handler=lambda db, target, owner: executor.execute(
            "operation", 0, owner
        ),
    )
    topology = SqlAlchemyMoveTopology(db_session)
    assert (
        topology.source("allowed-node", frozenset({"test-library"})).node_id
        == "allowed-node"
    )
    backup = root / "allowed" / plan.targets[0].file.backup_name
    assert backup.read_bytes() == original
    entries = store.expired_backups(3000 + 2 * 24 * 60 * 60_000)
    operation, ordinal, target, proof = entries[0]
    db_session.rollback()
    files.clear_backup(target.targets[ordinal].file, proof)
    store.backup_cleanup_result(
        operation, ordinal, 3000 + 2 * 24 * 60 * 60_000, failed=False
    )
    db_session.commit()
    assert (
        topology.source("allowed-node", frozenset({"test-library"})).node_id
        == "allowed-node"
    )


@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize("failure", ["validation", "preparation", "unexpected"])
def test_writeback_failure_does_not_block_batch_or_same_file_task(
    client, db_session, tmp_path, failure_index, failure
):
    from app.modules.metadata.application.standard_files import StandardMetadataError
    from app.modules.metadata.application.standard_writeback import (
        StandardPreparationError,
    )
    from app.modules.metadata.infrastructure.standard_publication import (
        StandardMetadataPublication,
    )
    from app.services.metadata_file_writeback import (
        recover_interrupted_metadata_writebacks,
    )
    from tests.integration.modules.automation.test_operation_management import cookie

    root, _, files, store, plan = prepared(db_session, tmp_path, batch=True)
    failed_file = plan.targets[failure_index].file

    class Files(StandardMetadataPublication):
        def prepare(self, target):
            if target.relative_path == failed_file.relative_path:
                if failure == "validation":
                    raise StandardMetadataError("SOURCE_CHANGED")
                if failure == "preparation":
                    proof = super().prepare(target)
                    raise StandardPreparationError(
                        "COPY_ATTRIBUTES_NOT_PRESERVED", proof.identity
                    )
                raise OSError("file preparation interrupted")
            return super().prepare(target)

    from app.modules.library.infrastructure.source_file_access import (
        open_library_directory,
        open_library_file,
    )

    failing_files = Files(open_library_directory, open_library_file)
    command = ExecuteStandardWrite(
        store,
        failing_files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
        diagnostics=failure_diagnostics(db_session),
    )

    def handler(db, target, owner):
        payload = target["payload"]
        command.execute(payload["standard_operation_id"], payload["ordinal"], owner)

    # Execute the selected failure first, independent of hashed queue ID order.
    from app.modules.metadata.infrastructure.writeback_queue import claim_next_target

    for ordinal in range(3):
        result = db_session.get(MetadataStandardWriteTarget, ("operation", ordinal))
        queued = db_session.get(MetadataWritebackTarget, result.queue_target_id)
        queued.created_at = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(
            seconds=(ordinal != failure_index)
        )
    db_session.commit()
    for _ in range(3):
        assert process_next_metadata_writeback(
            db_session, Settings(), standard_handler=handler
        )
    expected = ["COMPLETED"] * 3
    expected[failure_index] = (
        "FAILED" if failure == "validation" else "RECOVERY_REQUIRED"
    )
    assert [
        db_session.get(MetadataStandardWriteTarget, ("operation", i)).stage
        for i in range(3)
    ] == expected
    failed_result = db_session.get(
        MetadataStandardWriteTarget, ("operation", failure_index)
    )
    evidence = dict(failed_result.recovery)
    if failure != "validation":
        queue = db_session.get(MetadataWritebackTarget, failed_result.queue_target_id)
        assert queue.status == "REVIEW"
        assert queue.lease_owner_id is None and queue.lease_expires_at is None
    assert recover_interrupted_metadata_writebacks(db_session) == 0
    assert (
        claim_next_target(db_session, owner_id="restart", now=datetime.now(UTC)) is None
    )
    db_session.rollback()

    # A new task on the exact same file runs its own frozen plan, even with a retained .part.
    next_target = replace(
        plan.targets[failure_index],
        file=replace(
            failed_file,
            prepared_name=".ermao-mcp-" + "f" * 32 + "-target",
            backup_name=".ermao-mcp-" + "f" * 32 + "-source",
        ),
    )
    retry = replace(plan, id="retry-plan", targets=(next_target,))
    store.save(retry)
    store.enqueue(retry, "retry", "retry-request", 4000)
    db_session.commit()
    command = replace(command, files=files)
    assert process_next_metadata_writeback(
        db_session, Settings(), standard_handler=handler
    )
    assert (
        db_session.get(MetadataStandardWriteTarget, ("retry", 0)).stage == "COMPLETED"
    )
    assert (
        db_session.get(
            MetadataStandardWriteTarget, ("operation", failure_index)
        ).recovery
        == evidence
    )
    if failure == "preparation":
        assert (root / "allowed" / failed_file.prepared_name).exists()
    cookie(client, db_session)
    response = client.get("/api/automation/operations")
    assert response.status_code == 200
    operations = {
        item["operation_id"]: item for item in response.json()["data"]["operations"]
    }
    assert [item["stage"] for item in operations["operation"]["targets"]] == expected
    assert operations["retry"]["status"] == "COMPLETED"


def test_relocation_preserves_standard_tasks_and_recovery_results(db_session, tmp_path):
    from app.contracts.source_relocation import SourceRelocation
    from app.modules.metadata.infrastructure.writeback_queue import (
        discard_relocated_writebacks,
    )

    _, _, _, _, _ = prepared(db_session, tmp_path, batch=True)
    target = db_session.get(MetadataStandardWriteTarget, ("operation", 0))
    target.stage = "RECOVERY_REQUIRED"
    target.recovery = {"resume_stage": "PREPARING"}
    queue = db_session.get(MetadataWritebackTarget, target.queue_target_id)
    queue.status = "REVIEW"
    db_session.commit()
    change = SourceRelocation(
        "test-library",
        "allowed",
        "test-library",
        "renamed",
        ("allowed-node",),
        ("allowed",),
    )
    assert discard_relocated_writebacks(db_session, change) == 0
    db_session.commit()
    assert (
        db_session.scalar(select(func.count()).select_from(MetadataWritebackTarget))
        == 3
    )
    assert [
        db_session.get(MetadataStandardWriteTarget, ("operation", i)).stage
        for i in range(3)
    ] == ["RECOVERY_REQUIRED", "QUEUED", "QUEUED"]
