"""Best-effort I/O keeps its behavior and publishes each actual failure cause."""

import errno
import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.core.exception_diagnostics import (
    configure_exception_storage,
    exception_diagnostic_boundary,
    reset_exception_storage,
)
from app.infrastructure import atomic_files
from app.infrastructure import copied_file_attributes as attributes
from app.infrastructure.bounded_inspection import read_optional_file
from app.models.settings import SystemEvent


@pytest.fixture
def events(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'events.sqlite'}")
    SystemEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine)
    configure_exception_storage(factory)
    try:
        yield factory
    finally:
        reset_exception_storage()
        engine.dispose()


@pytest.mark.parametrize(
    "step", ["list_xattrs", "get_xattr", "set_xattr", "set_mode", "set_timestamps"]
)
def test_optional_attributes_keep_actual_errno_and_continue(
    step, tmp_path, monkeypatch, events, caplog
):
    path = tmp_path / "target"
    path.write_bytes(b"original")

    def denied(*args, **kwargs):
        raise OSError(
            errno.EACCES, f"{step} denied", "/private/books/private title.epub"
        )

    monkeypatch.setattr(attributes, "_list_attributes", lambda _: ("user.example",))
    monkeypatch.setattr(attributes, "_get_attribute", lambda *args: b"value")
    monkeypatch.setattr(attributes, "_set_attribute", lambda *args: None)
    methods = {
        "list_xattrs": (attributes, "_list_attributes"),
        "get_xattr": (attributes, "_get_attribute"),
        "set_xattr": (attributes, "_set_attribute"),
        "set_mode": (attributes.os, "fchmod"),
        "set_timestamps": (attributes.os, "utime"),
    }
    module, method = methods[step]
    monkeypatch.setattr(module, method, denied)
    with (
        exception_diagnostic_boundary(
            logging.getLogger(__name__),
            "attribute.test",
            context={"operation_id": "operation-attrs", "target_ordinal": 2},
        ),
        path.open("r+b") as handle,
    ):
        original = attributes.read_copy_attributes(handle.fileno())
        attributes.apply_copy_attributes(handle.fileno(), original)
    assert path.read_bytes() == b"original"
    with events() as db:
        rows = db.scalars(select(SystemEvent)).all()
    target = [row for row in rows if row.metadata_json["step"] == step]
    assert len(target) == 1
    metadata = target[0].metadata_json
    assert metadata["diagnostics"]["rootCause"]["errno"] == errno.EACCES
    assert metadata["operationId"] == "operation-attrs"
    assert metadata["targetOrdinal"] == 2
    assert target[0].id in caplog.text
    assert "private title" not in caplog.text


def test_optional_missing_sidecar_is_not_a_failure(tmp_path, events, caplog):
    assert read_optional_file(tmp_path / "missing.opf", 100) is None
    with events() as db:
        assert db.scalars(select(SystemEvent)).all() == []
    assert "read_optional_file.failed" not in caplog.text


def test_optional_sidecar_io_failure_is_not_missing(
    tmp_path, events, monkeypatch, caplog
):
    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "device read failed")

    monkeypatch.setattr(Path, "open", fail)
    assert read_optional_file(tmp_path / "metadata.opf", 100) is None
    with events() as db:
        row = db.scalars(select(SystemEvent)).one()
    assert row.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EIO
    assert "device read failed" in caplog.text


def test_atomic_replace_retry_records_each_actual_attempt(
    tmp_path, events, monkeypatch, caplog
):
    original_replace = atomic_files.os.replace
    attempts = 0

    def locked_then_succeeds(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            error = PermissionError(errno.EACCES, "sharing lock denied replace")
            error.winerror = 32
            raise error
        original_replace(source, destination)

    monkeypatch.setattr(atomic_files.os, "replace", locked_then_succeeds)
    monkeypatch.setattr(atomic_files, "sleep", lambda _: None)
    target = tmp_path / "published"
    atomic_files.write_atomic_bytes(target, b"complete")
    assert target.read_bytes() == b"complete"
    with events() as db:
        rows = db.scalars(select(SystemEvent)).all()
    assert len(rows) == 2
    assert {row.metadata_json["attempt"] for row in rows} == {1, 2}
    assert all(
        row.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EACCES
        for row in rows
    )
    assert all(row.id in caplog.text for row in rows)


def test_atomic_cleanup_failure_links_to_primary_failure(
    tmp_path, events, monkeypatch, caplog
):
    def fail_replace(*_args):
        raise OSError(errno.EROFS, "original publication read only")

    def fail_cleanup(*_args, **_kwargs):
        raise OSError(errno.EIO, "temporary cleanup I/O failure")

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(OSError, match="temporary cleanup"):
        atomic_files.write_atomic_bytes(tmp_path / "published", b"complete")
    with events() as db:
        rows = db.scalars(select(SystemEvent)).all()
    assert len(rows) == 2
    original = next(row for row in rows if row.action == "atomic_file.publish_failed")
    cleanup = next(row for row in rows if row.action == "atomic_file.cleanup_failed")
    assert cleanup.metadata_json["parentDiagnosticId"] == original.id
    assert original.metadata_json["diagnostics"]["rootCause"]["errno"] == errno.EROFS
    assert cleanup.metadata_json["diagnostics"]["directException"]["errno"] == errno.EIO
    assert original.id in caplog.text and cleanup.id in caplog.text
