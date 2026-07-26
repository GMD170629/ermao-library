from __future__ import annotations

import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from appv2.modules.ingestion.application.scanner import IngestionScanner
from appv2.modules.ingestion.contracts import ImportResult, MonitorFolder
from appv2.modules.ingestion.infrastructure.formats import (
    LocalPublicationPreparation,
    UnsafePublication,
)


class ScannerUnitOfWork:
    def __init__(self) -> None:
        self.ingestion = MagicMock()

    def __enter__(self) -> ScannerUnitOfWork:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


def _write_epub(path: Path, *, title: str = "Test Book") -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{title}</dc:title><dc:creator>Author</dc:creator>"
            "<dc:language>en</dc:language><dc:identifier>isbn:1</dc:identifier>"
            "</metadata><manifest/><spine/></package>",
        )


def test_epub_parser_extracts_stable_identity(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    _write_epub(source)
    parser = LocalPublicationPreparation(tmp_path / "conversions")

    publication = parser.prepare(str(source))

    assert publication.title == "Test Book"
    assert publication.author == "Author"
    assert publication.language == "en"
    assert publication.identifiers == ("isbn:1",)
    assert publication.files[0].source_path == str(source)


def test_comic_parser_rejects_unsafe_archive_paths(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.cbz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("../cover.jpg", b"not-an-image")
    parser = LocalPublicationPreparation(tmp_path / "conversions")

    with pytest.raises(UnsafePublication, match="invalid"):
        parser.prepare(str(source))


def test_txt_and_fb2_are_converted_and_keep_original_source(tmp_path: Path) -> None:
    text = tmp_path / "chapters.txt"
    text.write_text("Chapter 1\nHello\nChapter 2\nWorld", encoding="utf-8")
    fb2 = tmp_path / "book.fb2"
    fb2.write_text(
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
        "<description><title-info><book-title>FB2 Book</book-title><lang>zh-CN</lang>"
        "<author><first-name>First</first-name><last-name>Last</last-name></author>"
        "</title-info></description><body><section><p>Body</p></section></body>"
        "</FictionBook>",
        encoding="utf-8",
    )
    parser = LocalPublicationPreparation(tmp_path / "conversions")

    text_result = parser.prepare(str(text))
    fb2_result = parser.prepare(str(fb2))
    unconverted_text = parser.prepare(str(text), auto_convert_to_epub=False)

    assert text_result.format == "epub"
    assert text_result.metadata["chapterCount"] == 2
    assert text_result.files[1].source_path == str(text)
    assert unconverted_text.format == "txt"
    assert len(unconverted_text.files) == 1
    assert unconverted_text.files[0].source_path == str(text)
    assert fb2_result.title == "FB2 Book"
    assert fb2_result.author == "First Last"
    assert fb2_result.files[1].source_path == str(fb2)


def test_scanner_collapses_audio_tracks_into_one_bundle_job(tmp_path: Path) -> None:
    audio_root = tmp_path / "audiobook"
    audio_root.mkdir()
    tracks = [audio_root / "02.mp3", audio_root / "01.mp3"]
    ebook = tmp_path / "book.epub"
    unit = ScannerUnitOfWork()
    first_job_id = uuid.uuid4()
    unit.ingestion.observe_and_enqueue.side_effect = [
        ImportResult(first_job_id, "queued", None, None, (), False),
        ImportResult(first_job_id, "queued", None, None, (), True),
        ImportResult(uuid.uuid4(), "queued", None, None, (), False),
    ]
    scanner = IngestionScanner(
        uow_factory=lambda: unit,
        discovery=MagicMock(),
        stability_seconds=0,
    )
    folder = MonitorFolder(
        id=uuid.uuid4(),
        path=str(tmp_path),
        enabled=True,
        recursive=True,
        options={},
        last_scan_at=None,
        created_at=datetime.now(UTC),
    )

    queued, ignored = scanner._enqueue_candidates(
        folder=folder,
        paths=[str(tracks[0]), str(tracks[1]), str(ebook)],
        trigger="initial",
        requested_by=None,
    )

    assert (queued, ignored) == (2, 1)
    calls = unit.ingestion.observe_and_enqueue.call_args_list
    first_audio = calls[0].kwargs["request"]
    second_audio = calls[1].kwargs["request"]
    assert first_audio.source_path == str(tracks[1])
    assert second_audio.source_path == first_audio.source_path
    assert second_audio.idempotency_key == first_audio.idempotency_key
    assert calls[2].kwargs["request"].idempotency_key != first_audio.idempotency_key
