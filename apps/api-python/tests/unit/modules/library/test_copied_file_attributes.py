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
