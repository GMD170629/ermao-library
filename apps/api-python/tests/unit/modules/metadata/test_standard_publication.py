from dataclasses import replace

import pytest

from app.contracts.publication_metadata import PublicationMetadata
from app.infrastructure.file_identity import file_identity
from app.modules.library.infrastructure.source_file_access import (
    open_library_directory,
    open_library_file,
)
from app.modules.metadata.application.standard_files import StandardMetadataError
from app.modules.metadata.application.standard_writeback import StandardWriteFile
from app.modules.metadata.infrastructure import standard_publication
from app.modules.metadata.infrastructure.standard_publication import (
    StandardMetadataPublication,
)
from tests.unit.modules.metadata.test_selective_opf import SOURCE


def target(root):
    source = root / "book.opf"
    source.write_bytes(SOURCE)
    parent = root.stat()
    return StandardWriteFile(
        "library",
        root,
        "book.opf",
        parent.st_dev,
        parent.st_ino,
        "OPF",
        file_identity(source.stat()),
        PublicationMetadata(title="New"),
        frozenset({"title"}),
        ".ermao-mcp-" + "a" * 32 + "-target",
        ".ermao-mcp-" + "a" * 32 + "-source",
    )


def files():
    return StandardMetadataPublication(open_library_directory, open_library_file)


@pytest.mark.parametrize("interrupt_after", [0, 1, 2])
def test_publication_recovery_keeps_original_and_does_not_repeat_writes(
    tmp_path, monkeypatch, interrupt_after
):
    request = target(tmp_path)
    publisher = files()
    prepared = publisher.prepare(request)
    assert (tmp_path / "book.opf").read_bytes() == SOURCE
    assert not publisher.published(request, prepared)
    rename = standard_publication.exclusive_rename
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        rename(*args)
        if calls == interrupt_after:
            raise OSError("simulated publication interruption")

    monkeypatch.setattr(standard_publication, "exclusive_rename", interrupted)
    if interrupt_after:
        with pytest.raises(OSError):
            publisher.publish(request, prepared)
    publisher.publish(request, prepared)
    assert publisher.published(request, prepared)
    assert calls == 2
    assert (tmp_path / request.backup_name).read_bytes() == SOURCE
    assert b">New<" in (tmp_path / "book.opf").read_bytes()


def test_source_change_after_preparation_does_not_overwrite(tmp_path):
    request = target(tmp_path)
    publisher = files()
    prepared = publisher.prepare(request)
    (tmp_path / "book.opf").write_bytes(b"external change")
    with pytest.raises(StandardMetadataError, match="SOURCE_CHANGED"):
        publisher.publish(request, prepared)
    assert (tmp_path / "book.opf").read_bytes() == b"external change"
    assert not (tmp_path / request.backup_name).exists()


def test_new_opf_uses_exclusive_publication(tmp_path):
    request = target(tmp_path)
    (tmp_path / "book.opf").unlink()
    request = replace(request, original=None)
    publisher = files()
    prepared = publisher.prepare(request)
    publisher.publish(request, prepared)
    assert publisher.published(request, prepared)
    assert b">New<" in (tmp_path / "book.opf").read_bytes()
    assert not (tmp_path / request.backup_name).exists()


def test_inspection_validates_selected_fields_without_creating_files(tmp_path):
    request = target(tmp_path)
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    inspection = files().inspect(
        request.root,
        request.relative_path,
        request.format,
        request.values,
        request.fields,
    )
    assert inspection.original == request.original
    assert inspection.before.title == "Old"
    assert inspection.before.authors == ("Old author",)
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    with pytest.raises(StandardMetadataError, match="UNSUPPORTED_METADATA_FIELD"):
        files().inspect(
            request.root,
            request.relative_path,
            request.format,
            request.values,
            frozenset({"cover_href"}),
        )
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before


@pytest.mark.parametrize("staged_original", [False, True])
def test_cancel_prepared_restores_original_and_removes_only_known_slots(
    tmp_path, staged_original
):
    request = target(tmp_path)
    publisher = files()
    prepared = publisher.prepare(request)
    if staged_original:
        (tmp_path / "book.opf").rename(tmp_path / request.backup_name)
    publisher.discard_prepared(request, prepared)
    assert (tmp_path / "book.opf").read_bytes() == SOURCE
    assert sorted(item.name for item in tmp_path.iterdir()) == ["book.opf"]


def test_preparation_rejects_insufficient_space_without_creating_slots(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    request = target(tmp_path)
    monkeypatch.setattr(
        standard_publication.os,
        "fstatvfs",
        lambda _: SimpleNamespace(f_flag=0, f_bavail=0, f_frsize=4096),
    )
    with pytest.raises(StandardMetadataError, match="PREPARATION_SPACE_UNAVAILABLE"):
        files().prepare(request)
    assert sorted(item.name for item in tmp_path.iterdir()) == ["book.opf"]
    assert (tmp_path / "book.opf").read_bytes() == SOURCE


def test_read_only_source_is_rejected_during_preview(tmp_path):
    request = target(tmp_path)
    source = tmp_path / "book.opf"
    source.chmod(0o444)
    try:
        with pytest.raises(StandardMetadataError, match="READ_ONLY_FILE"):
            files().inspect(
                tmp_path,
                request.relative_path,
                request.format,
                request.values,
                request.fields,
            )
        assert sorted(item.name for item in tmp_path.iterdir()) == ["book.opf"]
    finally:
        source.chmod(0o644)
