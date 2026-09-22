import os
import subprocess
import sys

import pytest

from app.infrastructure.copied_file_attributes import (
    apply_copy_attributes,
    read_copy_attributes,
)


def test_copy_preserves_mode_time_and_user_attributes(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    os.chmod(source, 0o640)
    os.utime(source, ns=(1_700_000_000_000_000_000, 1_700_000_000_123_000_000))
    if sys.platform == "darwin":
        subprocess.run(
            ["xattr", "-w", "com.ermao.test", "retained", str(source)], check=True
        )
    else:
        os.setxattr(source, "user.ermao.test", b"retained")
    with source.open("rb") as first, target.open("r+b") as second:
        original = read_copy_attributes(first.fileno())
        apply_copy_attributes(second.fileno(), original)
        assert read_copy_attributes(second.fileno()) == original
        assert read_copy_attributes(first.fileno()) == original
    assert target.read_bytes() == b"target"


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin extended ACL API")
def test_copy_preserves_real_extended_acl(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    subprocess.run(["chmod", "+a", "everyone allow read", str(source)], check=True)
    with source.open("rb") as first, target.open("r+b") as second:
        original = read_copy_attributes(first.fileno())
        assert original.acl
        apply_copy_attributes(second.fileno(), original)
        assert read_copy_attributes(second.fileno()) == original


@pytest.mark.parametrize("failure", ["list", "read", "set", "mismatch", "acl"])
def test_optional_attribute_failures_do_not_block_other_attributes(
    tmp_path, monkeypatch, failure
):
    from app.contracts.file_operation import FileOperationError
    from app.infrastructure import copied_file_attributes as attributes

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    source.chmod(0o640)
    calls = []

    def names(_):
        if failure == "list":
            raise OSError("unavailable")
        return ("unavailable", "retained")

    def get(_, name):
        if failure == "read" and name == "unavailable":
            raise FileOperationError("COPY_ATTRIBUTES_UNAVAILABLE")
        return b"value"

    def put(_, name, value):
        calls.append(name)
        if failure == "set" and name == "unavailable":
            raise OSError("unsupported")
        # Simulate a successful syscall whose value is not retained.

    def acl(*_):
        raise FileOperationError("COPY_ACL_UNSUPPORTED")

    monkeypatch.setattr(attributes, "_list_attributes", names)
    monkeypatch.setattr(attributes, "_get_attribute", get)
    monkeypatch.setattr(attributes, "_set_attribute", put)
    if failure == "acl":
        monkeypatch.setattr(attributes, "_darwin_acl", acl)
    with source.open("rb") as first, target.open("r+b") as second:
        original = read_copy_attributes(first.fileno())
        apply_copy_attributes(second.fileno(), original)
    assert target.stat().st_mode & 0o777 == 0o640
    assert target.read_bytes() == b"target"
    assert calls == (
        []
        if failure == "list"
        else ["retained"]
        if failure == "read"
        else ["unavailable", "retained"]
    )


def test_attribute_handling_does_not_hide_programming_errors(tmp_path, monkeypatch):
    from app.infrastructure import copied_file_attributes as attributes

    def broken(_):
        raise RuntimeError("implementation defect")

    monkeypatch.setattr(attributes, "_list_attributes", broken)
    with (
        (tmp_path / "file").open("w+b") as file,
        pytest.raises(RuntimeError, match="implementation defect"),
    ):
        read_copy_attributes(file.fileno())


def test_permission_failure_still_attempts_timestamp(tmp_path, monkeypatch):
    from app.infrastructure import copied_file_attributes as attributes

    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"source")
    target.write_bytes(b"target")
    os.utime(source, ns=(1_700_000_000_000_000_000,) * 2)

    def denied(*_):
        raise PermissionError("not permitted")

    with source.open("rb") as first, target.open("r+b") as second:
        expected = read_copy_attributes(first.fileno())
        monkeypatch.setattr(attributes.os, "fchmod", denied)
        apply_copy_attributes(second.fileno(), expected)
    assert target.stat().st_mtime_ns == source.stat().st_mtime_ns
    assert target.read_bytes() == b"target"
