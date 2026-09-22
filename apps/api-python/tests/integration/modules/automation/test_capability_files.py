"""Permanent deletion and replacement operate only on frozen temporary sources."""

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
from app.models import LibraryImportTask
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import AutomationAccessError, Scope
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
        access.user_id, AutomationServiceSettings(True, access.permissions.scopes | upload_only.permissions.scopes, "http://localhost")
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


def test_delete_crash_after_unlink_recovers_without_touching_new_source(
    files, db_session, monkeypatch
):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("replace-node",))
    erase = service.files.files.erase

    def interrupted(target):
        erase(target)
        raise OSError("injected interruption")

    monkeypatch.setattr(service.files.files, "erase", interrupted)
    result = service.execute(access, plan["plan_id"])
    assert result["status"] == "RECOVERY_REQUIRED"
    (root / "allowed/book.cbz").write_bytes(b"new same name")
    monkeypatch.setattr(service.files.files, "erase", erase)
    result = service.execute(access, plan["plan_id"])
    assert result["targets"][0]["stage"] == "INDEX_PENDING"
    assert (root / "allowed/book.cbz").read_bytes() == b"new same name"


def test_delete_never_removes_unlisted_child(files, db_session, monkeypatch):
    access, root = files
    service = build_automation_deletions(db_session)
    plan = service.plan(access, ("allowed-node",))
    stage = service.files.files.stage

    def add_child(target):
        stage(target)
        (root / target.staging_path / "new.cbz").write_bytes(b"not frozen")

    monkeypatch.setattr(service.files.files, "stage", add_child)
    result = service.execute(access, plan["plan_id"])
    assert result["status"] == "RECOVERY_REQUIRED"
    assert next(iter(root.glob(".ermao-delete-*/new.cbz"))).read_bytes() == b"not frozen"


def test_replace_recovers_after_publication_checkpoint_loss(
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
    assert commands.complete(access, identifier)["status"] == "QUEUED"
    assert source.read_bytes() == data


def test_deleting_last_directory_cleans_index_without_disabling_empty_root_guard(files, db_session, test_settings):
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
