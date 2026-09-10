"""Exercise real import readers with source payload traps and read accounting."""

from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

import pytest

from app.infrastructure.comic_archives import inspect_comic_archive
from app.modules.imports.infrastructure.limited_read import (
    InspectionLimitReached,
    LimitedReader,
)
from app.modules.imports.infrastructure.reflowable_metadata import (
    inspect_reflowable_book,
)
from app.modules.imports.infrastructure.text_encoding import TXT_ENCODING_SAMPLE_BYTES
from app.services.audio_metadata import parse_audio_metadata


def test_reader_budget_counts_repeated_reads_and_rejects_read_all(tmp_path: Path):
    path = tmp_path / "source"
    path.write_bytes(b"123456789")
    with LimitedReader(path, budget=5) as source:
        assert source.read(3) == b"123"
        source.seek(0)
        assert source.read(2) == b"12"
        with pytest.raises(InspectionLimitReached):
            source.read(1)
    with LimitedReader(path) as source, pytest.raises(InspectionLimitReached):
        source.read()


def test_comic_reads_only_selected_cover_and_metadata(tmp_path: Path, monkeypatch):
    path = tmp_path / "book.cbz"
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        archive.writestr("cover.png", b"cover")
        for number in range(50):
            archive.writestr(f"{number:03}.jpg", b"body" * 50_000)
    original = ZipFile.open
    opened = []

    def observe(self, name, *args, **kwargs):
        opened.append(name.filename if hasattr(name, "filename") else name)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "open", observe)
    result = inspect_comic_archive(path)
    assert result["pageCount"] == 51
    assert opened == ["cover.png"]
    assert result["coverContent"] == b"cover"


@pytest.mark.parametrize("extension", ["mlp", "thd", "ogg", "opus", "wv"])
def test_audio_without_safe_tag_reader_never_starts_stream_probe(
    tmp_path, monkeypatch, extension
):
    path = tmp_path / f"audio.{extension}"
    path.write_bytes(b"payload" * 100_000)
    import app.services.audio_metadata as module

    monkeypatch.setattr(
        module, "_read_with_ffprobe", lambda *a, **kw: pytest.fail("stream probe")
    )
    result = parse_audio_metadata(path)
    assert result.duration_ms is None
    assert result.codec is None


def test_txt_encoding_does_not_verify_nul_tail(tmp_path, monkeypatch):
    path = tmp_path / "book.txt"
    path.write_bytes(
        b"hello\x00" + b"\x00" * (TXT_ENCODING_SAMPLE_BYTES + 10) + b"forbidden tail"
    )
    original = Path.open
    reads = []

    class ObservedFile:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def read(self, size=-1):
            assert size >= 0
            data = self.source.read(size)
            reads.append(len(data))
            return data

    def opened(self, *args, **kwargs):
        source = original(self, *args, **kwargs)
        return ObservedFile(source) if self == path else source

    monkeypatch.setattr(Path, "open", opened)
    result = inspect_reflowable_book(path, "TXT")
    assert result.raw_metadata["inputEncoding"] == "utf-8"
    assert sum(reads) == TXT_ENCODING_SAMPLE_BYTES + 3


def test_fb2_stops_before_body(tmp_path, monkeypatch):
    path = tmp_path / "book.fb2"
    description = b"<FictionBook><description><title-info><book-title>Title</book-title></title-info></description>"
    path.write_bytes(
        description + b"<body>" + b"body" * 100_000 + b"</body></FictionBook>"
    )
    original = Path.open

    class ObservedFile:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def read(self, size=-1):
            assert 0 <= size <= len(description) - self.source.tell()
            return self.source.read(size)

    monkeypatch.setattr(
        Path,
        "open",
        lambda self, *a, **kw: (
            ObservedFile(original(self, *a, **kw))
            if self == path
            else original(self, *a, **kw)
        ),
    )
    assert inspect_reflowable_book(path, "FB2").title == "Title"


def test_epub_reads_metadata_toc_and_cover_without_chapter(tmp_path, monkeypatch):
    from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
        RegistryResourceAdapterExecutor,
    )
    from app.modules.imports.domain.resource_adapters import (
        ADAPTER_SPECS,
        ResourceAdapterId,
    )

    path = tmp_path / "book.epub"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfile full-path="OPS/book.opf"/></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Title</dc:title></metadata><manifest><item id="toc" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>',
        )
        archive.writestr(
            "OPS/nav.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><nav epub:type="toc"><a href="chapter.xhtml">Chapter One</a></nav></html>',
        )
        archive.writestr("OPS/chapter.xhtml", b"forbidden body" * 100_000)
    original = ZipFile.open
    reads = []

    def opened(self, name, *args, **kwargs):
        member = name.filename if hasattr(name, "filename") else name
        assert member != "OPS/chapter.xhtml"
        reads.append(member)
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "open", opened)
    adapter = next(
        spec for spec in ADAPTER_SPECS if spec.adapter_id is ResourceAdapterId.EPUB
    )
    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path, adapter=adapter, role=adapter.asset_role
    )
    assert result.ok
    assert result.local_metadata.metadata.title == "Title"
    assert result.asset.navigation_units[0].title == "Chapter One"
    assert result.asset.navigation_units[0].href == "OPS/chapter.xhtml"
    assert reads == ["META-INF/container.xml", "OPS/book.opf", "OPS/nav.xhtml"]


def test_real_wave_metadata_reader_skips_audio_payload(tmp_path, monkeypatch):
    import wave

    path = tmp_path / "track.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800_000)
    original = LimitedReader.read
    reads = []

    def observed(self, size=-1):
        start = self.tell()
        result = original(self, size)
        reads.append((start, self.tell()))
        return result

    monkeypatch.setattr(LimitedReader, "read", observed)
    result = parse_audio_metadata(path)
    assert result.duration_ms == 100_000
    assert sum(end - start for start, end in reads) < 65558
    assert not any(start <= 500_000 < end for start, end in reads)
