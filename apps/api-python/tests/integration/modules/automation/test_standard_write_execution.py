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
from tests.integration.modules.automation.test_writeback_plans import opf, setup


def prepared(db, tmp_path):
    access, root, catalog, planner = setup(db, tmp_path)
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


def test_interruption_after_publication_repairs_without_second_write(
    db_session, tmp_path
):
    root, original, files, store, plan = prepared(db_session, tmp_path)

    def interrupted(*_):
        raise RuntimeError("simulated process failure before index commit")

    executor = ExecuteStandardWrite(
        store, files, lambda *_: None, interrupted, db_session, lambda: 3000
    )

    def handler(db, target, owner):
        executor.execute("operation", 0, owner)

    assert process_next_metadata_writeback(
        db_session, Settings(), standard_handler=handler
    )
    target = db_session.get(MetadataStandardWriteTarget, ("operation", 0))
    assert target.stage == "RECOVERY_REQUIRED"
    published_inode = (root / "allowed/metadata.opf").stat().st_ino

    def revoked(*_):
        raise AssertionError("published-file repair does not require revoked authority")

    resumed = ExecuteStandardWrite(
        store,
        files,
        revoked,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 4000,
    )
    assert store.recover_verified_targets(4000) == 1
    db_session.commit()
    assert process_next_metadata_writeback(
        db_session,
        Settings(),
        owner_id="restarted-worker",
        standard_handler=lambda db, target, owner: resumed.execute(
            "operation", 0, owner
        ),
    )
    assert (
        db_session.get(MetadataStandardWriteTarget, ("operation", 0)).stage
        == "COMPLETED"
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
    # A retained uncertain result still owns the file conflict scope.
    queue = db_session.get(MetadataWritebackTarget, claimed["id"])
    queue.status = "REVIEW"
    db_session.commit()
    assert scans.next_queued() is None


def test_completed_writeback_keeps_locator_until_verified_backup_cleanup(
    db_session, tmp_path
):
    import pytest

    from app.modules.library.infrastructure.move_topology import SqlAlchemyMoveTopology
    from app.modules.library.public import FileMoveError

    root, original, files, store, plan = prepared(db_session, tmp_path)
    executor = ExecuteStandardWrite(
        store,
        files,
        lambda *_: None,
        SqlAlchemyStandardWriteIndex(db_session).record,
        db_session,
        lambda: 3000,
    )
    assert process_next_metadata_writeback(
        db_session,
        Settings(),
        standard_handler=lambda db, target, owner: executor.execute(
            "operation", 0, owner
        ),
    )
    topology = SqlAlchemyMoveTopology(db_session)
    with pytest.raises(FileMoveError, match="RECOVERY_BACKUP_PENDING"):
        topology.source("allowed-node", frozenset({"test-library"}))
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
