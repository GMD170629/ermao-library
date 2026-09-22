import hashlib
import os

import pytest

from app.modules.library.domain.file_moves import FileMoveError
from app.modules.library.infrastructure.move_inventory import inspect_move_source
from app.modules.library.infrastructure.verified_file_copy import copy_verified_tree


@pytest.mark.parametrize("attribute_failure", [None, "read", "set", "mismatch"])
def test_verified_copy_preserves_bytes_and_keeps_source(
    tmp_path, monkeypatch, attribute_failure
):
    from app.infrastructure import copied_file_attributes as attributes

    def unavailable(*_):
        raise OSError("attribute unavailable")

    if attribute_failure:
        monkeypatch.setattr(
            attributes, "_list_attributes", lambda _: ("com.apple.provenance",)
        )
        monkeypatch.setattr(
            attributes,
            "_get_attribute",
            unavailable if attribute_failure == "read" else lambda *_: b"source",
        )
        monkeypatch.setattr(
            attributes,
            "_set_attribute",
            unavailable if attribute_failure == "set" else lambda *_: None,
        )
    source_root, destination_root = tmp_path / "source", tmp_path / "destination"
    (source_root / "book/pages").mkdir(parents=True)
    destination_root.mkdir()
    data = b"page bytes" * 300_000
    (source_root / "book/pages/page.jpg").write_bytes(data)
    (source_root / "book/metadata.opf").write_bytes(b"metadata")
    os.chmod(source_root / "book/pages/page.jpg", 0o640)
    inventory = inspect_move_source(source_root, "book")
    manifest = copy_verified_tree(
        source_root, "book", destination_root, ".move-stage", inventory
    )
    assert (destination_root / ".move-stage/metadata.opf").read_bytes() == b"metadata"
    assert len(manifest) == 2
    assert (
        next(
            item for item in manifest if item.relative_path.endswith("page.jpg")
        ).sha256
        == hashlib.sha256(data).hexdigest()
    )
    assert (destination_root / ".move-stage/pages/page.jpg").read_bytes() == data
    assert (source_root / "book/pages/page.jpg").read_bytes() == data
    assert inspect_move_source(source_root, "book") == inventory
    assert not (destination_root / "book").exists()


def test_copy_failure_keeps_source_and_does_not_publish(tmp_path, monkeypatch):
    import app.modules.library.infrastructure.verified_file_copy as copy_module

    source_root, destination_root = tmp_path / "source", tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / "book").write_bytes(b"original")
    inventory = inspect_move_source(source_root, "book")

    def failed_write(*_args):
        raise OSError("simulated disk full")

    monkeypatch.setattr(copy_module.os, "write", failed_write)
    with pytest.raises(OSError, match="disk full"):
        copy_verified_tree(
            source_root, "book", destination_root, ".move-stage", inventory
        )
    assert (source_root / "book").read_bytes() == b"original"
    assert not (destination_root / "book").exists()


def test_source_changed_or_existing_stage_is_never_overwritten(tmp_path):
    source_root, destination_root = tmp_path / "source", tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    source = source_root / "book"
    source.write_bytes(b"original")
    inventory = inspect_move_source(source_root, "book")
    (destination_root / ".stage").write_bytes(b"owned by another operation")
    with pytest.raises(FileExistsError):
        copy_verified_tree(source_root, "book", destination_root, ".stage", inventory)
    assert (destination_root / ".stage").read_bytes() == b"owned by another operation"
    source.write_bytes(b"changed")
    with pytest.raises(FileMoveError, match="SOURCE_CHANGED"):
        copy_verified_tree(
            source_root, "book", destination_root, ".new-stage", inventory
        )
    assert not (destination_root / ".new-stage").exists()


@pytest.mark.parametrize("failure", ["corrupt", "fsync"])
def test_content_or_persistence_failure_keeps_source(tmp_path, monkeypatch, failure):
    from app.modules.library.infrastructure import verified_file_copy as copy_module

    source_root, destination_root = tmp_path / "source", tmp_path / "destination"
    source_root.mkdir()
    destination_root.mkdir()
    (source_root / "book").write_bytes(b"original")
    inventory = inspect_move_source(source_root, "book")
    write = os.write

    def corrupt(fd, content):
        return write(fd, b"x" * len(content))

    def disk_error(_):
        raise OSError("persistence failed")

    if failure == "corrupt":
        monkeypatch.setattr(copy_module.os, "write", corrupt)
    else:
        monkeypatch.setattr(copy_module.os, "fsync", disk_error)
    with pytest.raises(
        (FileMoveError, OSError), match="COPY_VERIFICATION_FAILED|persistence failed"
    ):
        copy_verified_tree(source_root, "book", destination_root, ".stage", inventory)
    assert (source_root / "book").read_bytes() == b"original"
    assert not (destination_root / "book").exists()
