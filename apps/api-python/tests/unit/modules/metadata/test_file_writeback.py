from __future__ import annotations

import zipfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from app.modules.metadata.application.opf import parse_opf_metadata
from app.modules.metadata.infrastructure.file_writeback import (
    prepare_writeback,
    publish_prepared,
)


def _payload(path: Path, **values: object) -> dict[str, object]:
    stat = path.stat()
    return {
        "title": "新标题",
        "authors": ["新作者"],
        "description": None,
        "subjects": [],
        "seriesName": None,
        "seriesIndex": None,
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


def test_txt_sidecar_preserves_unknown_extensions_and_existing_nonempty_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")
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
    assert metadata.author == "新作者"
    assert metadata.description == "保留简介"
    assert b"vendor:custom" in content
    assert source.read_text() == "正文"


def test_txt_sidecar_round_trip_preserves_work_and_volume_titles(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.txt"
    source.write_text("正文")

    prepared = prepare_writeback(
        str(source),
        _payload(
            source,
            title="辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了",
            volumeTitle="辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 Vol.1",
            volumeIndex=1,
        ),
        tmp_path,
    )
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    metadata = parse_opf_metadata(output.read_bytes())
    assert (
        metadata.title == "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了"
    )
    assert metadata.volume_title == (
        "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 Vol.1"
    )
    assert metadata.volume_index == 1


def test_epub_writeback_preserves_content_and_can_be_parsed_again(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/content.opf",
            '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>旧标题</dc:title><dc:description>旧简介</dc:description></metadata><manifest><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine/></package>',
        )
        archive.writestr("OPS/chapter.xhtml", b"<html><body>unchanged</body></html>")

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    publish_prepared(str(source), str(prepared.prepared_path), prepared.output_hash)

    with zipfile.ZipFile(source) as archive:
        assert (
            archive.read("OPS/chapter.xhtml") == b"<html><body>unchanged</body></html>"
        )
        metadata = parse_opf_metadata(archive.read("OPS/content.opf"))
    assert metadata.title == "新标题"
    assert metadata.description == "旧简介"


def test_pdf_writeback_preserves_pages_and_updates_document_info(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    with source.open("wb") as output:
        writer.write(output)

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    publish_prepared(str(source), str(prepared.prepared_path), prepared.output_hash)

    reader = PdfReader(str(source))
    assert len(reader.pages) == 1
    assert reader.metadata is not None
    assert reader.metadata.title == "新标题"
    assert reader.metadata.author == "新作者"


def test_signed_pdf_is_preserved_and_downgrades_to_sidecar_warning(
    tmp_path: Path,
) -> None:
    source = tmp_path / "signed.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with source.open("wb") as output:
        writer.write(output)
    source.write_bytes(source.read_bytes() + b"\n/ByteRange [0 1 2 3]\n")
    original = source.read_bytes()

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    assert prepared.warning_code == "SIDECAR_FALLBACK"
    output, _size, _mtime = publish_prepared(
        str(source), str(prepared.prepared_path), prepared.output_hash
    )

    assert output == source.with_suffix(".opf")
    assert source.read_bytes() == original
    assert parse_opf_metadata(output.read_bytes()).title == "新标题"


def test_cbz_writeback_preserves_pages_and_adds_comic_info(tmp_path: Path) -> None:
    source = tmp_path / "book.cbz"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("001.jpg", b"page-one")

    prepared = prepare_writeback(
        str(source), _payload(source, seriesName="系列", seriesIndex=2), tmp_path
    )
    publish_prepared(str(source), str(prepared.prepared_path), prepared.output_hash)

    with zipfile.ZipFile(source) as archive:
        assert archive.read("001.jpg") == b"page-one"
        comic_info = archive.read("ComicInfo.xml")
    assert "新标题" in comic_info.decode()
    assert "<Series>新标题</Series>" in comic_info.decode()


def test_fb2_writeback_preserves_body(tmp_path: Path) -> None:
    source = tmp_path / "book.fb2"
    source.write_text(
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"><description><title-info><book-title>旧标题</book-title><annotation>旧简介</annotation></title-info></description><body><section><p>正文不变</p></section></body></FictionBook>'
    )

    prepared = prepare_writeback(str(source), _payload(source), tmp_path)
    publish_prepared(str(source), str(prepared.prepared_path), prepared.output_hash)

    content = source.read_text()
    assert "新标题" in content
    assert "旧简介" in content
    assert "正文不变" in content
