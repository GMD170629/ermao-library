"""Standard source deletion and replacement preserve task ownership and outcomes."""

import errno
import hashlib
from dataclasses import replace

import pytest
from sqlalchemy import select

from app.bootstrap.automation import (
    build_automation_deletions,
    build_automation_settings,
    build_automation_uploads,
    build_grant_manager,
)
from app.contracts.automation_upload import UploadSpec
from app.infrastructure.file_operation_conflicts import file_operation_blocks_library
from app.models import FileDeletePlanRow, Library, LibraryImportTask, SystemEvent
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import AutomationAccessError, Scope
from app.modules.library.domain.file_moves import FileMoveError
from tests.integration.modules.automation.test_file_reads import add_file, file_access
from tests.integration.modules.automation.test_uploads import transmit


@pytest.fixture
def files(db_session, tmp_path, monkeypatch, test_settings):
    monkeypatch.setattr("app.bootstrap.automation.get_settings", lambda: test_settings)
    access, root = file_access(db_session, tmp_path)
    permissions = replace(
        access.permissions, scopes=frozenset({Scope.SYSTEM_READ, Scope.FILES_MODIFY})
    )
    build_automation_settings(db_session).update(
        access.user_id,
        AutomationServiceSettings(True, permissions.scopes, "http://localhost"),
    )
    grant = build_grant_manager(db_session).create(
        user_id=access.user_id, name="files", permissions=permissions
    )
    access = replace(access, grant_id=grant.grant.id, permissions=permissions)

    (root / "allowed/book.cbz").write_bytes(b"original")
    add_file(db_session, "replace-node", "allowed/book.cbz")
    db_session.commit()
    return access, root


def test_permanent_delete_and_replay_preserve_new_same_name(files, db_session):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    assert (root / "allowed/book.cbz").read_bytes() == b"original"
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "INDEX_PENDING", result
    assert not (root / "allowed/book.cbz").exists()
    (root / "allowed/book.cbz").write_bytes(b"later")
    service.execute(access, plan["plan_id"])
    assert (root / "allowed/book.cbz").read_bytes() == b"later"
    assert len(list(db_session.scalars(select(LibraryImportTask)))) == 1


def test_delete_rejects_changed_source(files, db_session):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    (root / "allowed/book.cbz").write_bytes(b"changed")
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["error_code"] == "DELETE_TARGET_FAILED"
    assert (root / "allowed/book.cbz").read_bytes() == b"changed"
    assert list(db_session.scalars(select(LibraryImportTask))) == []


def test_replace_exact_bytes_and_upload_only_rejected(files, db_session):
    access, root = files
    source = root / "allowed/book.cbz"
    info = source.stat()
    version = hashlib.sha256(f"{info.st_size}:{info.st_mtime_ns}".encode()).hexdigest()
    data = b"new complete container"
    specification = UploadSpec(
        "replace",
        "book.cbz",
        len(data),
        hashlib.sha256(data).hexdigest(),
        library_id="test-library",
        source_node_id="replace-node",
        expected_source_version=version,
    )
    commands = build_automation_uploads(db_session)
    upload_only = replace(
        access,
        permissions=replace(
            access.permissions,
            scopes=frozenset({Scope.SYSTEM_READ, Scope.FILES_UPLOAD}),
        ),
    )
    build_automation_settings(db_session).update(
        access.user_id,
        AutomationServiceSettings(
            True,
            access.permissions.scopes | upload_only.permissions.scopes,
            "http://localhost",
        ),
    )
    limited = build_grant_manager(db_session).create(
        user_id=access.user_id, name="upload only", permissions=upload_only.permissions
    )
    upload_only = replace(upload_only, grant_id=limited.grant.id)
    with pytest.raises(AutomationAccessError):
        commands.begin_upload(upload_only, specification, "forbidden")
    identifier = transmit(commands, access, specification, data)
    result = commands.complete(access, identifier)
    assert result["status"] == "QUEUED", result
    assert source.read_bytes() == data
    assert commands.complete(access, identifier)["file_saved"] is True
    assert list(root.rglob(".ermao-mcp-*-source")) == []


def test_deleted_source_index_reconciles_with_existing_import_worker(
    files, db_session, test_settings
):
    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.models import LibrarySourceNode

    access, _root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    service.execute(access, plan["plan_id"])
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    assert build_readable_resource_worker(pipeline).process_once() == "scan"
    db_session.expire_all()
    assert db_session.get(LibrarySourceNode, "replace-node") is None
    assert service.progress(access, plan["plan_id"])["status"] == "COMPLETED"


def test_delete_crash_after_unlink_does_not_replay_or_touch_new_source(
    files, db_session, monkeypatch, caplog
):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    delete = service.files.files.delete

    def interrupted(target):
        delete(target)
        raise OSError("injected interruption")

    monkeypatch.setattr(service.files.files, "delete", interrupted)
    result = service.execute(access, plan["plan_id"])
    assert result["status"] == "RECOVERY_REQUIRED"
    (root / "allowed/book.cbz").write_bytes(b"new same name")
    monkeypatch.setattr(service.files.files, "delete", delete)
    result = service.execute(access, plan["plan_id"])
    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["targets"][0]["stage"] == "DELETING"
    assert (root / "allowed/book.cbz").read_bytes() == b"new same name"
    assert list(db_session.scalars(select(LibraryImportTask))) == []
    event = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.action == "file_delete.previous_result_unavailable",
            SystemEvent.target_id == plan["plan_id"],
        )
    )
    assert event is not None and event.id in caplog.text
    assert event.metadata_json["step"] == "inspect_recovery_state"
    assert event.metadata_json["diagnostics"]["causeStatus"] == "NOT_PROVIDED"
    assert (
        "previous deletion result was not provided"
        in event.metadata_json["diagnostics"]["message"]
    )


def test_directory_delete_uses_standard_deletion_for_all_current_contents(
    files, db_session, monkeypatch
):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("allowed-node",))
    delete = service.files.files.delete
    outside = root.parent / "outside.cbz"
    outside.write_bytes(b"not part of the directory")

    def add_child(target):
        (root / "allowed/new.cbz").write_bytes(b"added after the preview")
        (root / "allowed/outside.cbz").symlink_to(outside)
        delete(target)

    monkeypatch.setattr(service.files.files, "delete", add_child)
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "INDEX_PENDING"
    assert not (root / "allowed").exists()
    assert list(root.iterdir()) == []
    assert outside.read_bytes() == b"not part of the directory"


def test_replace_preserves_file_without_replay_after_publication_checkpoint_loss(
    files, db_session, monkeypatch
):
    access, root = files
    source = root / "allowed/book.cbz"
    info = source.stat()
    version = hashlib.sha256(f"{info.st_size}:{info.st_mtime_ns}".encode()).hexdigest()
    data = b"replacement"
    specification = UploadSpec(
        "replace",
        "book.cbz",
        len(data),
        hashlib.sha256(data).hexdigest(),
        library_id="test-library",
        source_node_id="replace-node",
        expected_source_version=version,
    )
    commands = build_automation_uploads(db_session)
    identifier = transmit(commands, access, specification, data)
    publisher = commands._gateway(specification).publisher
    original = publisher.publish_strict

    def crash(publication):
        original(publication)
        raise OSError("lost checkpoint")

    monkeypatch.setattr(publisher, "publish_strict", crash)
    with pytest.raises(OSError):
        commands.complete(access, identifier)
    assert source.read_bytes() == data
    monkeypatch.setattr(publisher, "publish_strict", original)
    assert commands.complete(access, identifier)["status"] == "RECOVERY_REQUIRED"
    assert source.read_bytes() == data
    assert list(db_session.scalars(select(LibraryImportTask))) == []
    assert list(root.rglob(".ermao-mcp-*-source")) == []


def test_deleting_last_directory_cleans_index_without_disabling_empty_root_guard(
    files, db_session, test_settings
):
    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.models import LibrarySourceNode

    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("allowed-node",))
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "INDEX_PENDING"
    assert list(root.iterdir()) == []
    assert db_session.get(LibrarySourceNode, "allowed-node") is None
    pipeline = build_readable_resource_pipeline(db_session, test_settings)
    assert build_readable_resource_worker(pipeline).process_once() == "scan"
    assert service.progress(access, plan["plan_id"])["status"] == "COMPLETED"


def test_delete_cancel_before_execution_preserves_files(files, db_session):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("allowed-node",))
    service.cancel(access, plan["plan_id"])
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "CANCELLED"
    assert (root / "allowed/book.cbz").read_bytes() == b"original"
    assert list(db_session.scalars(select(LibraryImportTask))) == []


@pytest.mark.parametrize("stage", ["QUEUED", "STAGING", "STAGED", "FILES_DELETED"])
def test_legacy_delete_is_readable_and_cancellable_but_never_replayed(
    files, db_session, stage
):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    row = db_session.get(FileDeletePlanRow, plan["plan_id"])
    payload = dict(row.payload)
    assert payload.pop("execution_version") == 2
    staging = "allowed/.ermao-delete-legacy"
    if stage in {"STAGING", "STAGED"}:
        (root / "allowed/book.cbz").rename(root / staging)
        (root / "allowed/book.cbz").write_bytes(b"new same name")
    payload["targets"] = [
        {**payload["targets"][0], "stage": stage, "staging_path": staging}
    ]
    payload["executing"] = stage != "QUEUED"
    row.payload = payload
    db_session.commit()

    with pytest.raises(FileMoveError, match="DELETE_PLAN_REQUIRES_REFRESH"):
        service.execute(access, plan["plan_id"])
    assert service.progress(access, plan["plan_id"])["targets"][0]["stage"] == stage
    assert service.cancel(access, plan["plan_id"])["cancel_requested"] is True
    expected = b"new same name" if stage in {"STAGING", "STAGED"} else b"original"
    assert (root / "allowed/book.cbz").read_bytes() == expected
    if stage in {"STAGING", "STAGED"}:
        assert (root / staging).read_bytes() == b"original"
    assert list(db_session.scalars(select(LibraryImportTask))) == []


def test_delete_failure_retains_diagnostics_and_is_not_retried(
    files, db_session, monkeypatch
):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    calls = 0

    def denied(**_kwargs):
        nonlocal calls
        calls += 1
        assert (
            db_session.scalar(
                select(file_operation_blocks_library(Library.id)).where(
                    Library.id == "test-library"
                )
            )
            is True
        )
        raise PermissionError(errno.EACCES, "source deletion denied")

    monkeypatch.setattr(service.files.files.filesystem, "delete_source", denied)
    result = service.execute(access, plan["plan_id"])
    assert result["status"] == "RECOVERY_REQUIRED"
    event = db_session.scalar(
        select(SystemEvent).where(SystemEvent.action == "file_delete.target_failed")
    )
    assert event.metadata_json["step"] == "delete_files"
    assert event.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EACCES
    service.execute(access, plan["plan_id"])
    assert calls == 1
    assert (root / "allowed/book.cbz").read_bytes() == b"original"
    assert list(db_session.scalars(select(LibraryImportTask))) == []


def test_delete_rejects_a_source_replaced_by_symlink(files, db_session, tmp_path):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    outside = tmp_path / "outside.cbz"
    outside.write_bytes(b"outside the library")
    source = root / "allowed/book.cbz"
    source.unlink()
    source.symlink_to(outside)
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "FAILED"
    assert source.is_symlink()
    assert outside.read_bytes() == b"outside the library"
