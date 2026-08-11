from __future__ import annotations

import os
from pathlib import Path

import pytest
from app.modules.imports.infrastructure.sidecar_opf import discover_sidecar_opf
from app.modules.metadata.application.opf import parse_opf_metadata
from app.modules.metadata.infrastructure.file_writeback import (
    MetadataWritebackError,
    cleanup_orphan_prepared_files,
    output_path_for,
    prepare_writeback,
    publish_prepared,
)
from lxml import etree


def _payload(path: Path, **values: object) -> dict[str, object]:
    stat = path.stat()
    return {
        "title": "新标题",
        "volumeTitle": "第一卷",
        "authors": ["新作者"],
        "narrators": [],
        "abridged": None,
        "description": None,
        "subjects": [],
        "seriesName": None,
        "seriesIndex": None,
        "volumeIndex": 1,
        "language": None,
        "publisher": None,
        "publishedAt": None,
        "identifier": None,
        "isbn": None,
        "coverPath": None,
        "sourceSize": stat.st_size,
        "sourceMtimeMs": int(stat.st_mtime * 1000),
        **values,
    }


@pytest.mark.parametrize(
    "suffix",
    [
        ".epub",
        ".pdf",
        ".cbz",
        ".zip",
        ".fb2",
        ".mp3",
        ".flac",
        ".m4b",
        ".ogg",
        ".mobi",
        ".azw3",
        ".cbr",
        ".rar",
        ".txt",
    ],
)
def test_every_book_format_writes_opf_without_mutating_source(
    tmp_path: Path, suffix: str
) -> None:
    source = tmp_path / f"book{suffix}"
    original = b"source-book-bytes\x00must-not-change"
    source.write_bytes(original)
    original_stat = source.stat()

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    assert prepared.output_path == source.with_suffix(".opf")
    assert prepared.warning_code is None
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    assert output == source.with_suffix(".opf")
    assert source.read_bytes() == original
    assert source.stat().st_size == original_stat.st_size
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns
    metadata = parse_opf_metadata(output.read_bytes())
    assert metadata.title == "新标题"
    assert metadata.volume_title == "第一卷"
    assert metadata.author == "新作者"


def test_sidecar_preserves_extensions_and_clears_removed_managed_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"immutable epub")
    sidecar = source.with_suffix(".opf")
    sidecar.write_text(
        """<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
        <dc:title>旧标题</dc:title><dc:description>保留简介</dc:description>
        <meta name="vendor:custom" content="keep-me"/>
        </metadata><manifest/><spine/></package>"""
    )

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    content = output.read_bytes()
    metadata = parse_opf_metadata(content)
    assert metadata.title == "新标题"
    assert metadata.description is None
    assert b"vendor:custom" in content
    assert source.read_bytes() == b"immutable epub"


def test_audiobook_fields_and_work_series_index_round_trip_independently(
    tmp_path: Path,
) -> None:
    source = tmp_path / "audio.m4b"
    source.write_bytes(b"immutable audio")

    prepared = prepare_writeback(
        str(source),
        _payload(
            source,
            narrators=["甲", "乙"],
            abridged=True,
            seriesName="作品系列",
            seriesIndex=23,
            volumeIndex=2,
        ),
        tmp_path,
    )
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    metadata = parse_opf_metadata(output.read_bytes())
    assert metadata.narrators == ("甲", "乙")
    assert metadata.abridged is True
    assert metadata.series_name == "作品系列"
    assert metadata.series_index == 23
    assert metadata.volume_index == 2
    assert source.read_bytes() == b"immutable audio"


def test_cover_is_written_beside_opf_and_referenced_with_real_media_type(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.pdf"
    source.write_bytes(b"immutable pdf")
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\ncover")

    prepared = prepare_writeback(
        str(source), _payload(source, coverPath=str(cover)), tmp_path
    )
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    package = etree.fromstring(output.read_bytes())
    cover_item = next(
        node
        for node in package.iter()
        if etree.QName(node).localname == "item" and node.get("id") == "cover-image"
    )
    assert cover_item.get("href") == "book.cover.png"
    assert cover_item.get("media-type") == "image/png"
    assert output.with_name("book.cover.png").read_bytes() == cover.read_bytes()
    assert source.read_bytes() == b"immutable pdf"
    discovered = discover_sidecar_opf(source, directory_fallback=False)
    assert discovered is not None
    assert discovered.metadata.title == "新标题"
    assert discovered.cover_path == output.with_name("book.cover.png")


def test_directory_book_writes_metadata_opf_without_changing_contents(
    tmp_path: Path,
) -> None:
    source = tmp_path / "audio-book"
    source.mkdir()
    chapter = source / "01.mp3"
    chapter.write_bytes(b"immutable chapter")

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    assert output == source / "metadata.opf"
    assert chapter.read_bytes() == b"immutable chapter"
    assert parse_opf_metadata(output.read_bytes()).title == "新标题"


def test_direct_source_replacement_cannot_be_recovered_as_a_publish_target(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"immutable epub")
    legacy_direct_temporary = tmp_path / ".book.epub.shuku-old.part"
    legacy_direct_temporary.write_bytes(b"mutated epub")

    with pytest.raises(MetadataWritebackError, match="OPF 旁车"):
        output_path_for(str(source), str(legacy_direct_temporary))


def test_opf_metadata_file_is_never_treated_as_a_mutable_source_book(
    tmp_path: Path,
) -> None:
    source = tmp_path / "metadata.opf"
    original = b"existing metadata file"
    source.write_bytes(original)

    with pytest.raises(MetadataWritebackError, match="不能作为源图书"):
        prepare_writeback(str(source), _payload(source), tmp_path)

    assert source.read_bytes() == original


def test_orphan_cleanup_is_bounded_to_stale_unprotected_parts(
    tmp_path: Path,
) -> None:
    old = tmp_path / ".book.opf.shuku-old.part"
    recent = tmp_path / ".book.opf.shuku-recent.part"
    protected = tmp_path / ".book.opf.shuku-protected.part"
    unrelated = tmp_path / "keep.part"
    nested = tmp_path / "nested"
    nested.mkdir()
    nested_old = nested / ".book.opf.shuku-nested.part"
    for path in (old, recent, protected, unrelated, nested_old):
        path.write_bytes(b"temporary")
    old_timestamp = 1_000.0
    for path in (old, protected, nested_old):
        os.utime(path, (old_timestamp, old_timestamp))

    removed = cleanup_orphan_prepared_files(
        (tmp_path,),
        protected_paths=frozenset({protected}),
        now_seconds=old_timestamp + 24 * 60 * 60 + 1,
    )

    assert removed == 1
    assert not old.exists()
    assert recent.exists()
    assert protected.exists()
    assert unrelated.exists()
    assert nested_old.exists()
