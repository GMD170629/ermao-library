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


def test_same_size_replacement_changes_millisecond_reader_identity(tmp_path):
    request = target(tmp_path)
    source = tmp_path / "book.opf"
    # Canonicalize once, then change an equal-length title in a second operation.
    prepared = files().prepare(request)
    files().publish(request, prepared)
    before = source.stat()
    second = replace(
        request,
        original=file_identity(before),
        values=PublicationMetadata(title="Old"),
        prepared_name=".ermao-mcp-" + "b" * 32 + "-target",
        backup_name=".ermao-mcp-" + "b" * 32 + "-source",
    )
    import asyncio

    from fastapi import Request

    from app.modules.media.infrastructure.http_streaming import send_file

    def http_request(headers=()):
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/assets/fixture",
                "headers": list(headers),
                "query_string": b"",
            }
        )

    original_content = source.read_bytes()
    active = send_file(source, http_request(), "user", asset_id="fixture")
    old_version = active.headers["x-asset-version"]
    proof = files().prepare(second)
    files().publish(second, proof)
    after = source.stat()
    assert after.st_size == before.st_size
    assert after.st_mtime_ns // 1_000_000 > before.st_mtime_ns // 1_000_000
    assert b">Old<" in source.read_bytes()
    assert (tmp_path / second.backup_name).stat().st_mtime_ns == before.st_mtime_ns

    async def consume(response):
        chunks = [chunk async for chunk in response.body_iterator]
        if response.background is not None:
            await response.background()
        return b"".join(chunks)

    assert asyncio.run(consume(active)) == original_content
    stale = send_file(
        source,
        http_request(((b"x-asset-version", old_version.encode()),)),
        "user",
        asset_id="fixture",
    )
    assert stale.status_code == 412
    fresh = send_file(source, http_request(), "user", asset_id="fixture")
    assert fresh.headers["x-asset-version"] != old_version
    assert asyncio.run(consume(fresh)) == source.read_bytes()


@pytest.mark.parametrize("failure", ["read", "set", "mismatch"])
def test_cbz_publication_succeeds_despite_optional_attributes(
    tmp_path, monkeypatch, failure
):
    from zipfile import ZipFile

    from app.infrastructure import copied_file_attributes as attributes

    request = target(tmp_path)
    comic = tmp_path / "book.cbz"
    page = b"unchanged comic page bytes"
    with ZipFile(comic, "w") as archive:
        archive.writestr("001.jpg", page)
    original = comic.read_bytes()
    request = replace(
        request,
        relative_path="book.cbz",
        format="CBZ",
        original=file_identity(comic.stat()),
    )

    def unavailable(*_):
        raise OSError("attribute unavailable")

    monkeypatch.setattr(
        attributes, "_list_attributes", lambda _: ("com.apple.provenance",)
    )
    monkeypatch.setattr(
        attributes,
        "_get_attribute",
        unavailable if failure == "read" else lambda *_: b"source",
    )
    monkeypatch.setattr(
        attributes,
        "_set_attribute",
        unavailable if failure == "set" else lambda *_: None,
    )
    publisher = files()
    proof = publisher.prepare(request)
    publisher.publish(request, proof)
    assert publisher.published(request, proof)
    assert (tmp_path / request.backup_name).read_bytes() == original
    with ZipFile(comic) as archive:
        assert archive.read("001.jpg") == page
        assert b">New<" in archive.read("ComicInfo.xml")


def test_publication_persistence_failure_does_not_replace_original(
    tmp_path, monkeypatch
):
    from app.modules.metadata.application.standard_writeback import (
        StandardPreparationError,
    )

    request = target(tmp_path)

    def failed(_):
        raise OSError("persistence failed")

    monkeypatch.setattr(standard_publication.os, "fsync", failed)
    with pytest.raises(StandardPreparationError, match="FILE_PREPARATION_FAILED"):
        files().prepare(request)
    assert (tmp_path / request.relative_path).read_bytes() == SOURCE
    assert not (tmp_path / request.backup_name).exists()
