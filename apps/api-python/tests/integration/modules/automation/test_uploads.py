"""Exact-byte MCP attachment transfers using real journals and publication."""

import base64
import errno
import hashlib
from dataclasses import replace
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bootstrap.automation import (
    build_automation_catalog,
    build_automation_operation_manager,
    build_automation_settings,
    build_automation_uploads,
    build_grant_manager,
)
from app.contracts.automation_upload import UploadError, UploadSpec
from app.models import LibraryBookMetadata, LibraryImportTask, SystemEvent
from app.modules.automation.application.settings import AutomationServiceSettings
from app.modules.automation.domain.access import AutomationAccessError, Scope
from tests.integration.modules.automation.test_file_reads import file_access


def upload_access(db, tmp_path, monkeypatch, test_settings):
    monkeypatch.setattr("app.bootstrap.automation.get_settings", lambda: test_settings)
    access, root = file_access(db, tmp_path)
    access = replace(
        access,
        permissions=replace(
            access.permissions,
            scopes=access.permissions.scopes | {Scope.FILES_UPLOAD, Scope.BOOKS_WRITE},
        ),
    )
    build_automation_settings(db).update(
        access.user_id,
        AutomationServiceSettings(True, access.permissions.scopes, "http://localhost"),
    )
    grant = build_grant_manager(db).create(
        user_id=access.user_id, name="uploads", permissions=access.permissions
    )
    access = replace(access, grant_id=grant.grant.id)

    return access, root


@pytest.fixture
def uploads(db_session, tmp_path, monkeypatch, test_settings):
    access, root = upload_access(db_session, tmp_path, monkeypatch, test_settings)
    return build_automation_uploads(db_session), access, root


def spec(data, filename="test.epub", **kw):
    return UploadSpec(
        "book",
        filename,
        len(data),
        hashlib.sha256(data).hexdigest(),
        library_id="test-library",
        **kw,
    )


def transmit(commands, access, specification, data, request="test"):
    initial = commands.begin_upload(access, specification, request)
    for offset in range(0, len(data), 256 * 1024):
        commands.chunk(
            access,
            initial["upload_id"],
            offset,
            base64.b64encode(data[offset : offset + 256 * 1024]).decode(),
        )
    return initial["upload_id"]


def test_resumable_exact_bytes_idempotent_and_operation_list(uploads, db_session):
    commands, access, root = uploads
    data = b"book" * 100000
    specification = spec(data, directory_node_id="allowed-node")
    initial = commands.begin_upload(access, specification, "book-request")
    upload_id = initial["upload_id"]
    first = base64.b64encode(data[: 256 * 1024]).decode()
    assert commands.chunk(access, upload_id, 0, first)["received_bytes"] == 256 * 1024
    assert commands.chunk(access, upload_id, 0, first)["received_bytes"] == 256 * 1024
    with pytest.raises(UploadError, match="OFFSET"):
        commands.chunk(access, upload_id, 256 * 1024 + 1, "YQ==")
    with pytest.raises(UploadError, match="CHUNK_CONFLICT"):
        commands.chunk(access, upload_id, 0, "YQ==")
    db_session.rollback()
    with Session(db_session.get_bind()) as restarted:
        commands = build_automation_uploads(restarted)
        assert commands.progress(access, upload_id)["received_bytes"] == 256 * 1024
        commands.chunk(
            access, upload_id, 256 * 1024, base64.b64encode(data[256 * 1024 :]).decode()
        )
        result = commands.complete(access, upload_id)
        assert result["status"] == "QUEUED"
        assert (root / "allowed/test.epub").read_bytes() == data
        assert commands.complete(access, upload_id)["result"] == result["result"]
        assert (
            commands.begin_upload(access, specification, "book-request")["upload_id"]
            == upload_id
        )
        assert (
            restarted.scalar(select(func.count()).select_from(LibraryImportTask)) == 1
        )
        history = build_automation_operation_manager(restarted).recent(access.user_id)
        assert history[0].kind == "book_upload" and history[0].received_bytes == len(
            data
        )


def test_conflict_and_digest_failure_do_not_affect_next_upload(uploads):
    commands, access, root = uploads
    (root / "test.epub").write_bytes(b"original")
    bad = transmit(commands, access, spec(b"new"), b"new")
    assert commands.complete(access, bad)["error_code"] == "UPLOAD_NAME_CONFLICT"
    assert (root / "test.epub").read_bytes() == b"original"
    digest = transmit(
        commands,
        access,
        replace(spec(b"new", "bad.epub"), sha256="0" * 64),
        b"new",
        "digest",
    )
    assert commands.complete(access, digest)["error_code"] == "UPLOAD_DIGEST_MISMATCH"
    good = transmit(commands, access, spec(b"good", "good.epub"), b"good", "good")
    assert commands.complete(access, good)["status"] == "QUEUED"
    assert (root / "good.epub").read_bytes() == b"good"


def image_bytes(fmt="PNG"):
    output = BytesIO()
    Image.new("RGB", (20, 30), "blue").save(output, format=fmt)
    return output.getvalue()


def cover_spec(commands, access, db, data, **kw):
    revision = build_automation_catalog(db).get_metadata_schema(
        access, "book", "allowed"
    )["expected_revision"]
    return UploadSpec(
        "cover",
        "cover.png",
        len(data),
        hashlib.sha256(data).hexdigest(),
        book_id="allowed",
        expected_revision=revision,
        **kw,
    )


def test_cover_revision_protection_and_invalid_image(
    uploads, db_session, test_settings
):
    commands, access, _ = uploads
    data = image_bytes()
    original = cover_spec(commands, access, db_session, data)
    upload_id = transmit(commands, access, original, data)
    result = commands.complete(access, upload_id)
    assert result["status"] == "COMPLETED", result
    metadata = db_session.get(LibraryBookMetadata, "allowed", populate_existing=True)
    path = metadata.cover_path
    assert (test_settings.resolved_storage_root / path).read_bytes() == data
    assert "cover_path" in metadata.protected_fields
    assert result["result"]["revision"] != original.expected_revision
    assert commands.complete(access, upload_id) == result
    with pytest.raises(UploadError, match="METADATA_CONFLICT"):
        commands.begin_upload(access, original, "stale")
    with pytest.raises(UploadError, match="METADATA_PROTECTED"):
        commands.begin_upload(
            access, cover_spec(commands, access, db_session, data), "protected"
        )
    bad = b"invalid image"
    bad_id = transmit(
        commands,
        access,
        cover_spec(commands, access, db_session, bad, override=True),
        bad,
        "bad-cover",
    )
    assert commands.complete(access, bad_id)["error_code"] == "INVALID_COVER_IMAGE"
    assert (
        db_session.get(
            LibraryBookMetadata, "allowed", populate_existing=True
        ).cover_path
        == path
    )


def test_revocation_isolation_and_cancel(uploads, db_session):
    commands, access, root = uploads
    upload_id = commands.begin_upload(access, spec(b"ab"), "a")["upload_id"]
    other = build_grant_manager(db_session).create(
        user_id=access.user_id, name="other", permissions=access.permissions
    )
    with pytest.raises(UploadError, match="RESOURCE_NOT_FOUND"):
        commands.chunk(replace(access, grant_id=other.grant.id), upload_id, 0, "YQ==")
    build_grant_manager(db_session).revoke(
        user_id=access.user_id, grant_id=access.grant_id
    )
    with pytest.raises(AutomationAccessError):
        commands.chunk(access, upload_id, 0, "YQ==")
    manager = build_automation_operation_manager(db_session)
    assert manager.cancel(access.user_id, upload_id).status == "CANCELLED"
    assert not (root / "test.epub").exists()


@pytest.mark.parametrize("mode", ["FLAT", "VOLUMES"])
def test_published_book_reaches_actual_import_completion(
    uploads, db_session, test_settings, tmp_path, mode
):
    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.models import Library
    from tests.integration.modules.imports.test_volumes_metadata_pipeline import (
        _write_epub,
    )

    commands, access, root = uploads
    library = db_session.get(Library, "test-library")
    library.organization_mode = mode
    library.min_file_size_bytes = 0
    db_session.commit()
    source = tmp_path / "original.epub"
    _write_epub(source, title="Upload title", author="Author", cover=image_bytes())
    data = source.read_bytes()
    upload_id = transmit(
        commands, access, spec(data, directory_node_id="allowed-node"), data
    )
    assert commands.complete(access, upload_id)["status"] == "QUEUED"
    worker = build_readable_resource_worker(
        build_readable_resource_pipeline(db_session, test_settings)
    )
    for _ in range(20):
        if worker.process_once() == "idle":
            break
    result = commands.progress(access, upload_id)
    assert result["status"] == "COMPLETED", result
    assert result["result"]["book_ids"] and result["result"]["resource_ids"]
    assert (root / "allowed/test.epub").read_bytes() == data
    conflicting = transmit(
        commands,
        access,
        spec(data, directory_node_id="allowed-node"),
        data,
        "duplicate-name",
    )
    assert commands.complete(access, conflicting)["status"] == "FAILED"
    results = {
        item.operation_id: item.status
        for item in build_automation_operation_manager(db_session).recent(
            access.user_id
        )
    }
    assert results[upload_id] == "COMPLETED" and results[conflicting] == "FAILED"


def test_failure_after_publish_is_not_replayed_and_keeps_diagnostic(
    uploads, db_session, monkeypatch
):
    commands, access, root = uploads
    upload_id = transmit(commands, access, spec(b"bytes"), b"bytes")
    original = commands.books.publish

    def crash(publication):
        original(publication)
        raise OSError(errno.EIO, "simulated publication failure")

    monkeypatch.setattr(commands.books, "publish", crash)
    with pytest.raises(OSError):
        commands.complete(access, upload_id)
    assert (root / "test.epub").read_bytes() == b"bytes"
    with Session(db_session.get_bind()) as restarted:
        commands = build_automation_uploads(restarted)
        assert commands.complete(access, upload_id)["status"] == "RECOVERY_REQUIRED"
        assert (
            restarted.scalar(select(func.count()).select_from(LibraryImportTask)) == 0
        )
        event = restarted.scalar(
            select(SystemEvent).where(SystemEvent.action == "upload.complete_failed")
        )
        assert event.metadata_json["operationId"] == upload_id
        assert event.metadata_json["step"] == "publish_upload"
        assert event.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EIO


def test_unacknowledged_bytes_retry_and_expiry_cleanup(uploads):
    commands, access, _root = uploads
    upload_id = commands.begin_upload(access, spec(b"ab"), "pending")["upload_id"]
    with commands.files.lock(upload_id):
        commands.files.append(upload_id, 0, 0, b"wrong uncommitted bytes")
    assert commands.chunk(access, upload_id, 0, "YWI=")["received_bytes"] == 2
    later = replace(
        commands, clock_ms=lambda: commands.clock_ms() + 25 * 60 * 60 * 1000
    )
    later.cleanup()
    assert commands.progress(access, upload_id)["status"] == "EXPIRED"
    assert not (commands.files.root / f"{upload_id}.part").exists()
    assert commands.store.capacity(access.grant_id) == (0, 0)


def test_quota_limits_symlinks_and_changed_target(uploads, db_session, tmp_path):
    commands, access, root = uploads
    with pytest.raises(UploadError, match="INVALID_UPLOAD"):
        commands.begin_upload(
            access, replace(spec(b"a"), size_bytes=8 * 1024**3 + 1), "big"
        )
    with pytest.raises(UploadError, match="INVALID_UPLOAD"):
        commands.begin_upload(access, spec(b"a", "../escape.epub"), "escape")
    with pytest.raises(UploadError, match="RESOURCE_NOT_FOUND"):
        commands.begin_upload(
            access, replace(spec(b"a"), library_id="private-library"), "private"
        )
    (root / "allowed").rmdir()
    (root / "allowed").symlink_to(tmp_path)
    with pytest.raises(UploadError):
        commands.begin_upload(
            access, spec(b"a", directory_node_id="allowed-node"), "symlink"
        )
    (root / "allowed").unlink()
    (root / "allowed").mkdir()
    for i in range(20):
        commands.begin_upload(access, spec(b"a"), f"quota-{i}")
    with pytest.raises(UploadError, match="UPLOAD_QUOTA_EXCEEDED"):
        commands.begin_upload(access, spec(b"a"), "quota-exceeded")


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_cover_can_be_served_and_history_reports_upload(
    client, uploads, db_session, fmt
):
    from tests.integration.modules.automation.test_operation_management import cookie

    commands, access, _ = uploads
    data = image_bytes(fmt)
    upload_id = transmit(
        commands, access, cover_spec(commands, access, db_session, data), data
    )
    result = commands.complete(access, upload_id)
    assert result["status"] == "COMPLETED"
    cookie(client, db_session)
    cover = client.get(result["result"]["cover_url"])
    assert cover.status_code == 200, cover.text
    with Image.open(BytesIO(cover.content)) as image:
        assert image.size[0] > 0
    history = client.get("/api/automation/operations")
    assert history.status_code == 200
    upload = history.json()["data"]["operations"][0]
    assert upload["kind"] == "cover_upload"
    assert upload["status"] == "COMPLETED" and upload["file_saved"]
    assert upload["upload_result"]["revision"] == result["result"]["revision"]


def test_version_changed_after_transfer_and_publish_failure_keep_old_cover(
    uploads, db_session, monkeypatch
):
    commands, access, _ = uploads
    data = image_bytes()
    first = transmit(
        commands, access, cover_spec(commands, access, db_session, data), data
    )
    assert commands.complete(access, first)["status"] == "COMPLETED"
    old = db_session.get(LibraryBookMetadata, "allowed").cover_path
    second = transmit(
        commands,
        access,
        cover_spec(commands, access, db_session, data, override=True),
        data,
        "second",
    )
    metadata = db_session.get(LibraryBookMetadata, "allowed")
    metadata.title = "Intervening edit"
    db_session.commit()
    assert commands.complete(access, second)["error_code"] == "METADATA_CONFLICT"
    third = transmit(
        commands,
        access,
        cover_spec(commands, access, db_session, data, override=True),
        data,
        "third",
    )

    def fail(*args, **kwargs):
        raise OSError("disk failure with private path")

    monkeypatch.setattr(commands.covers.publication, "publish", fail)
    with pytest.raises(OSError):
        commands.complete(access, third)
    assert (
        db_session.get(
            LibraryBookMetadata, "allowed", populate_existing=True
        ).cover_path
        == old
    )


def test_database_failure_never_acknowledges_or_loses_original_confirmed_offset(
    uploads, db_session, monkeypatch
):
    commands, access, _ = uploads
    upload_id = commands.begin_upload(access, spec(b"ab"), "db-failure")["upload_id"]
    original = db_session.commit

    def fail():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db_session, "commit", fail)
    with pytest.raises(RuntimeError):
        commands.chunk(access, upload_id, 0, "YWI=")
    db_session.rollback()
    monkeypatch.setattr(db_session, "commit", original)
    assert commands.progress(access, upload_id)["received_bytes"] == 0
    assert commands.chunk(access, upload_id, 0, "YWI=")["received_bytes"] == 2


def test_upload_schema_new_install_and_upgrade(tmp_path):
    from alembic import command
    from sqlalchemy import inspect

    from app.db.runner import alembic_config_for_engine
    from app.db.sqlite import create_sqlite_engine

    for old in (False, True):
        engine = create_sqlite_engine(tmp_path / f"schema-{old}.sqlite3")
        try:
            config = alembic_config_for_engine(engine)
            if old:
                command.upgrade(config, "0026_automation_grant_secrets")
                assert "AutomationUpload" not in inspect(engine).get_table_names()
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            assert "AutomationUpload" in inspect(engine).get_table_names()
            assert {
                c["name"] for c in inspect(engine).get_columns("AutomationUpload")
            } == {
                "id",
                "userId",
                "grantId",
                "libraryId",
                "status",
                "sizeBytes",
                "createdAt",
                "expiresAt",
                "payload",
                "cleanupAfter",
            }
        finally:
            engine.dispose()


def test_active_lock_blocks_duplicate_call_without_blocking_other_uploads(uploads):
    commands, access, _ = uploads
    first = commands.begin_upload(access, spec(b"a"), "lock-first")["upload_id"]
    second = commands.begin_upload(access, spec(b"a", "other.epub"), "lock-second")[
        "upload_id"
    ]
    with commands.files.lock(first):
        with pytest.raises(UploadError, match="UPLOAD_BUSY"):
            commands.chunk(access, first, 0, "YQ==")
        commands.chunk(access, second, 0, "YQ==")
        assert commands.complete(access, second)["status"] == "QUEUED"
    assert commands.chunk(access, first, 0, "YQ==")["received_bytes"] == 1


def test_incomplete_publication_copy_is_reprepared_on_retry(uploads):
    commands, access, root = uploads
    upload_id = transmit(commands, access, spec(b"original bytes"), b"original bytes")
    (root / f".upload-{upload_id}.part").write_bytes(b"orig")
    assert commands.complete(access, upload_id)["status"] == "QUEUED"
    assert (root / "test.epub").read_bytes() == b"original bytes"


def test_expiry_preserves_book_published_before_checkpoint(uploads, monkeypatch):
    commands, access, root = uploads
    upload_id = transmit(commands, access, spec(b"published"), b"published")
    original = commands.books.publish

    def crash(publication):
        original(publication)
        raise OSError("interrupted checkpoint")

    monkeypatch.setattr(commands.books, "publish", crash)
    with pytest.raises(OSError):
        commands.complete(access, upload_id)
    replace(
        commands, clock_ms=lambda: commands.clock_ms() + 25 * 60 * 60 * 1000
    ).cleanup()
    assert (root / "test.epub").read_bytes() == b"published"
    assert commands.progress(access, upload_id)["status"] == "RECOVERY_REQUIRED"
    assert (commands.files.root / f"{upload_id}.part").exists()


def test_unavailable_expired_targets_do_not_starve_other_cleanup(
    uploads, db_session, monkeypatch
):
    commands, access, _ = uploads
    for index in range(20):
        commands.begin_upload(access, spec(b"a"), f"cleanup-{index}")
    other = build_grant_manager(db_session).create(
        user_id=access.user_id, name="other", permissions=access.permissions
    )
    other_access = replace(access, grant_id=other.grant.id)
    last = commands.begin_upload(other_access, spec(b"a"), "last")["upload_id"]
    original = commands.books.discard

    def unavailable(upload_id, target, publication):
        if upload_id != last:
            raise UploadError("UPLOAD_TARGET_CHANGED")
        return original(upload_id, target, publication)

    monkeypatch.setattr(commands.books, "discard", unavailable)
    # Deterministic two passes: the first batch's failures receive cleanup backoff.
    later = replace(
        commands, clock_ms=lambda: commands.clock_ms() + 25 * 60 * 60 * 1000
    )
    later.cleanup()
    later.cleanup()
    assert commands.store.get(
        last, access.user_id, other_access.grant_id
    ).staging_cleaned


def test_scan_continuation_is_not_misreported_as_unrecognized(uploads, db_session):
    commands, access, _ = uploads
    upload_id = transmit(
        commands, access, spec(b"book", directory_node_id="allowed-node"), b"book"
    )
    result = commands.complete(access, upload_id)
    task = db_session.get(LibraryImportTask, result["result"]["task_id"])
    task.state = "SUCCEEDED"
    db_session.add(
        LibraryImportTask(
            id="continued",
            kind="CONTINUE_SOURCE",
            library_id="test-library",
            source_node_id="allowed-node",
            state="QUEUED",
        )
    )
    db_session.commit()
    assert commands.progress(access, upload_id)["status"] == "IMPORTING"
    db_session.get(LibraryImportTask, "continued").state = "SUCCEEDED"
    db_session.commit()
    assert commands.progress(access, upload_id)["status"] == "FAILED"


def test_upload_digest_is_verified_once_before_standard_library_copy(
    uploads, monkeypatch
):
    commands, access, root = uploads
    data = b"one transfer verification"
    upload_id = transmit(commands, access, spec(data), data)
    verify = commands.files.verify
    verified = []

    def verify_once(*args):
        verified.append(args[0])
        return verify(*args)

    def unexpected_digest(*args, **kwargs):
        raise AssertionError("publication must not hash the copied upload again")

    monkeypatch.setattr(commands.files, "verify", verify_once)
    monkeypatch.setattr(hashlib, "file_digest", unexpected_digest)
    result = commands.complete(access, upload_id)
    assert result["status"] == "QUEUED"
    assert commands.complete(access, upload_id)["status"] == "QUEUED"
    assert verified == [upload_id]
    assert (root / "test.epub").read_bytes() == data


def test_saved_upload_retries_only_scan_registration(
    uploads, db_session, monkeypatch
):
    commands, access, root = uploads
    upload_id = transmit(commands, access, spec(b"saved"), b"saved")
    register = commands.books.register

    def unavailable(*args):
        raise OSError(errno.EIO, "scan queue unavailable")

    monkeypatch.setattr(commands.books, "register", unavailable)
    with pytest.raises(OSError):
        commands.complete(access, upload_id)
    pending = commands.progress(access, upload_id)
    assert pending["status"] == "RECOVERY_REQUIRED" and pending["file_saved"]
    assert (root / "test.epub").read_bytes() == b"saved"

    def forbidden(*args):
        raise AssertionError("a saved upload must not be published again")

    monkeypatch.setattr(commands.books, "register", register)
    monkeypatch.setattr(commands.books, "prepare", forbidden)
    monkeypatch.setattr(commands.books, "publish", forbidden)
    assert commands.complete(access, upload_id)["status"] == "QUEUED"
    assert db_session.scalar(select(func.count()).select_from(LibraryImportTask)) == 1


def test_legacy_upload_publication_and_backup_are_retained_without_replay(
    uploads, db_session
):
    from app.modules.automation.infrastructure.upload_schema import AutomationUploadRow

    commands, access, root = uploads
    upload_id = transmit(commands, access, spec(b"legacy"), b"legacy")
    record = commands.store.get(upload_id, access.user_id, access.grant_id)
    source = commands.files.verify(upload_id, record.spec.size_bytes, record.spec.sha256)
    publication = commands.books.prepare(upload_id, record.spec, record.target, source)
    backup = root / f".ermao-mcp-{upload_id}-source"
    backup.write_bytes(b"historical backup")
    commands.store.save(
        replace(
            record,
            status="PUBLISHING",
            publication=replace(publication, backup_name=backup.name),
        )
    )
    db_session.commit()
    row = db_session.get(AutomationUploadRow, upload_id)
    payload = dict(row.payload)
    payload.pop("execution_version")
    payload["publication"].pop("execution_version")
    row.payload = payload
    db_session.commit()
    result = commands.complete(access, upload_id)
    assert result["status"] == "RECOVERY_REQUIRED"
    assert result["error_code"] == "UPLOAD_PLAN_REQUIRES_REFRESH"
    replace(
        commands, clock_ms=lambda: commands.clock_ms() + 25 * 60 * 60 * 1000
    ).cleanup()
    assert not (root / "test.epub").exists()
    assert (root / publication.staged_name).read_bytes() == b"legacy"
    assert backup.read_bytes() == b"historical backup"
    assert (commands.files.root / f"{upload_id}.part").read_bytes() == b"legacy"
    assert db_session.scalar(select(func.count()).select_from(LibraryImportTask)) == 0


@pytest.mark.parametrize("scan_fails", [False, True])
def test_partial_browser_upload_keeps_files_requests_existing_scan_and_reports_failure(
    client, uploads, db_session, monkeypatch, test_settings, scan_fails
):
    from app.bootstrap.readable_resource_pipeline import (
        build_readable_resource_pipeline,
        build_readable_resource_worker,
    )
    from app.models import Library, LibrarySourceNode
    from app.modules.imports.infrastructure.uploaded_file_publication import (
        AtomicUploadedFilePublisher,
    )
    from tests.integration.modules.automation.test_operation_management import cookie

    _, _, root = uploads
    db_session.get(Library, "test-library").min_file_size_bytes = 0
    db_session.commit()
    cookie(client, db_session)
    copy = AtomicUploadedFilePublisher._copy_stream
    calls = 0

    def fail_second(source, target, *, max_bytes):
        nonlocal calls
        calls += 1
        if calls == 2:
            target.write_bytes(b"partial")
            raise OSError(errno.ENOSPC, "injected storage failure")
        return copy(source, target, max_bytes=max_bytes)

    monkeypatch.setattr(
        AtomicUploadedFilePublisher, "_copy_stream", staticmethod(fail_second)
    )
    if scan_fails:
        def failed_scan(*args, **kwargs):
            raise OSError(errno.EIO, "scan request failed")

        monkeypatch.setattr(
            "app.modules.imports.presentation.writes.continue_library_import",
            failed_scan,
        )
    response = client.post(
        "/api/books/import",
        headers={"Origin": "http://testserver"},
        data={"targetPath": str(root)},
        files=[
            ("files", ("saved.txt", b"Saved readable text.", "text/plain")),
            ("files", ("failed.txt", b"Later upload.", "text/plain")),
        ],
    )
    assert response.status_code == 500, response.text
    assert (root / "saved.txt").read_bytes() == b"Saved readable text."
    assert not (root / "failed.txt").exists()
    assert next(root.glob(".upload-*.part")).read_bytes() == b"partial"
    primary = db_session.scalar(
        select(SystemEvent).where(
            SystemEvent.action
            == "modules.imports.presentation.writes.import_book_files.failed"
        )
    )
    assert primary.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.ENOSPC
    assert response.headers["X-Error-Id"] == primary.id
    if scan_fails:
        secondary = db_session.scalar(
            select(SystemEvent).where(SystemEvent.action == "upload.partial_batch_scan_failed")
        )
        assert secondary.metadata_json["parentDiagnosticId"] == primary.id
        assert secondary.metadata_json["diagnostics"]["directException"]["errno"] == errno.EIO
        assert secondary.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EIO
        assert secondary.metadata_json["diagnostics"]["directCause"] is None
        assert secondary.metadata_json["diagnostics"]["contextProvided"] is True
        assert any(
            item.get("errno") == errno.ENOSPC
            for item in secondary.metadata_json["diagnostics"]["chain"]
        )
    else:
        worker = build_readable_resource_worker(
            build_readable_resource_pipeline(db_session, test_settings)
        )
        assert worker.process_once() == "scan"
        assert db_session.scalar(
            select(LibrarySourceNode.id).where(
                LibrarySourceNode.relative_path == "saved.txt"
            )
        ) is not None
