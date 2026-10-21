from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest

from app.modules.imports.infrastructure.reflowable_metadata import (
    inspect_reflowable_book,
)


def test_txt_inspection_reads_metadata_without_generating_navigation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "测试小说.txt"
    source.write_text(
        "第一章 开始\n正文。\n第二章 继续\n正文。\n后记\n结束。",
        encoding="utf-8",
    )

    metadata = inspect_reflowable_book(source, "TXT")

    assert metadata.title is None
    assert metadata.language == "zh-CN"
    assert "navigationCount" not in metadata.raw_metadata
    assert "navigationFingerprint" not in metadata.raw_metadata


@pytest.mark.parametrize("content", [
    "正文".encode("gbk"),
    "正文".encode("gbk") + b"\xff" + "结束".encode("gbk"),
    b"\x00" + "正文".encode("gbk") + b"\x00" + "结束".encode("gbk"),
    ("�" * 20 + "正文").encode("gb18030"),
    b"\xef\xbb\xbfA\xffB",
    b"",
])
def test_txt_inspection_tolerates_bytes_without_error_logs_or_source_changes(
    tmp_path, monkeypatch, caplog, content,
):
    from app.modules.system.infrastructure import log_files

    monkeypatch.setattr(log_files, "_root", tmp_path / "logs")
    source = tmp_path / "book.txt"
    source.write_bytes(content)
    metadata = inspect_reflowable_book(source, "TXT")
    assert metadata.raw_metadata["inputEncoding"] in {"utf-8", "utf-8-sig", "gb18030"}
    assert source.read_bytes() == content
    assert not [record for record in caplog.records if record.levelname == "ERROR"]
    assert not list((tmp_path / "logs" / "api").glob("*.jsonl"))


def test_txt_sample_does_not_treat_a_partial_character_as_file_eof():
    from app.modules.publications.public import decode_txt_bytes

    assert decode_txt_bytes(b"A\x81", final=False).text == "A"
    assert decode_txt_bytes(b"A\x81", final=True).text == "A�"
    assert decode_txt_bytes(b"\xef\xbb\xbfA\xe4", final=False).text == "A"
    assert decode_txt_bytes(b"\xef\xbb\xbfA\xe4", final=True).text == "A�"


def test_txt_error_beyond_bounded_sample_does_not_prevent_import(tmp_path):
    from app.modules.imports.infrastructure.reflowable_metadata import (
        TXT_ENCODING_SAMPLE_BYTES,
    )
    from app.modules.publications.public import decode_txt_bytes

    content = b"A" * (TXT_ENCODING_SAMPLE_BYTES + 3) + b"\xffB"
    source = tmp_path / "late-error.txt"
    source.write_bytes(content)
    metadata = inspect_reflowable_book(source, "TXT")
    assert metadata.raw_metadata["inputEncoding"] == "utf-8"
    assert decode_txt_bytes(content).text.endswith("�B")
    assert source.read_bytes() == content


def test_txt_inspection_uses_matching_sidecar_cover(tmp_path: Path) -> None:
    source = tmp_path / "novel.txt"
    source.write_text("Chapter One\nBody", encoding="utf-8")
    source.with_suffix(".jpg").write_bytes(b"\xff\xd8\xff\xe0cover")

    metadata = inspect_reflowable_book(source, "TXT")

    assert metadata.cover is not None
    assert metadata.cover.media_type == "image/jpeg"
    assert metadata.raw_metadata["coverSidecar"] is True


def test_fb2_inspection_reads_description_without_scanning_for_tail_cover(
    tmp_path: Path,
) -> None:
    cover = base64.b64encode(b"\x89PNG\r\n\x1a\ncover").decode("ascii")
    source = tmp_path / "book.fb2"
    source.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:l="http://www.w3.org/1999/xlink">
 <description><title-info><genre>detective</genre><author><first-name>东野</first-name>
 <last-name>圭吾</last-name></author><book-title>魔法石</book-title><lang>zh-CN</lang>
 <sequence name="哈利波特" number="1"/>
 <coverpage><image l:href="#cover"/></coverpage></title-info>
 <publish-info><publisher>测试出版社</publisher></publish-info></description>
 <body><section id="one"><title><p>第一章</p></title><p>正文</p></section>
 <section><title><p>第二章</p></title><p>正文</p></section></body>
 <binary id="cover" content-type="image/png">{cover}</binary>
</FictionBook>""",
        encoding="utf-8",
    )

    metadata = inspect_reflowable_book(source, "FB2")

    assert metadata.title == "魔法石"
    assert metadata.series_name == "哈利波特"
    assert metadata.series_index == 1
    assert metadata.authors == ("东野圭吾",)
    assert metadata.publisher == "测试出版社"
    assert "navigationCount" not in metadata.raw_metadata
    assert metadata.cover is None  # Cover is after body; import must not scan for it.


def test_mobi_inspection_reads_metadata_without_generating_navigation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.mobi"
    source.write_bytes(_synthetic_mobi())

    metadata = inspect_reflowable_book(source, "MOBI")

    assert metadata.title == "放学后"
    assert metadata.authors == ("东野圭吾",)
    assert metadata.publisher == "测试出版社"
    assert metadata.language == "zh-CN"
    assert "chapterSource" not in metadata.raw_metadata
    assert "navigationCount" not in metadata.raw_metadata
    assert "navigationFingerprint" not in metadata.raw_metadata
    assert metadata.cover is not None
    assert metadata.cover.media_type == "image/jpeg"


def test_mobi_inspection_reads_paired_structured_series_records(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.azw3"
    source.write_bytes(
        _synthetic_mobi(
            extra_exth_records=[
                _exth_text(112, "银河帝国"),
                _exth_text(113, "2.5"),
            ]
        )
    )

    metadata = inspect_reflowable_book(source, "AZW3")

    assert metadata.series_name == "银河帝国"
    assert metadata.series_index == 2.5
    assert metadata.identifier == "42"
    assert metadata.raw_metadata["seriesName"] == "银河帝国"
    assert metadata.raw_metadata["seriesIndex"] == "2.5"


def test_mobi_source_and_asin_are_not_misclassified_as_series(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.mobi"
    source.write_bytes(
        _synthetic_mobi(
            extra_exth_records=[
                _exth_text(112, "calibre:550e8400-e29b-41d4-a716-446655440000"),
                _exth_text(113, "B012345678"),
            ]
        )
    )

    metadata = inspect_reflowable_book(source, "MOBI")

    assert metadata.series_name is None
    assert metadata.series_index is None
    assert metadata.identifier == "B012345678"


def _synthetic_mobi(
    *, extra_exth_records: list[bytes] | None = None, body: bytes | None = None
) -> bytes:
    record_zero = bytearray(420)
    struct.pack_into(">H", record_zero, 0, 1)
    struct.pack_into(">H", record_zero, 8, 1)
    record_zero[16:20] = b"MOBI"
    struct.pack_into(">I", record_zero, 20, 232)
    struct.pack_into(">I", record_zero, 28, 65001)
    struct.pack_into(">I", record_zero, 32, 42)
    struct.pack_into(">I", record_zero, 36, 6)
    struct.pack_into(">I", record_zero, 108, 2)
    struct.pack_into(">I", record_zero, 128, 0x40)
    exth_records = [
        _exth_text(503, "放学后"),
        _exth_text(100, "东野圭吾"),
        _exth_text(101, "测试出版社"),
        _exth_text(524, "zh-CN"),
        _exth_uint(201, 0),
        *(extra_exth_records or []),
    ]
    exth = b"EXTH" + struct.pack(
        ">II", 12 + sum(map(len, exth_records)), len(exth_records)
    )
    exth += b"".join(exth_records)
    record_zero[248 : 248 + len(exth)] = exth
    navigation = (
        '<h1>第一章</h1><a filepos="0000000010">第一节</a>'
        '<a filepos="0000000040">第二节</a>'
        '<a filepos="9999999999">越界章节</a><h1>第二章</h1>'
    ).encode()
    cover = b"\xff\xd8\xff\xe0synthetic-cover"
    records = [bytes(record_zero), body if body is not None else navigation, cover]
    header_size = 78 + len(records) * 8
    pdb = bytearray(header_size)
    pdb[60:64] = b"BOOK"
    pdb[64:68] = b"MOBI"
    struct.pack_into(">H", pdb, 76, len(records))
    offset = header_size
    for index, record in enumerate(records):
        struct.pack_into(">I", pdb, 78 + index * 8, offset)
        offset += len(record)
    return bytes(pdb) + b"".join(records)


def _exth_text(record_type: int, value: str) -> bytes:
    content = value.encode("utf-8")
    return struct.pack(">II", record_type, len(content) + 8) + content


def _exth_uint(record_type: int, value: int) -> bytes:
    return struct.pack(">III", record_type, 12, value)


def test_mobi_reads_metadata_and_far_cover_without_body(tmp_path, monkeypatch):
    path = tmp_path / "large.mobi"
    content = _synthetic_mobi(body=b"forbidden body" * 500_000)
    body_start = struct.unpack_from(">I", content, 86)[0]
    body_end = struct.unpack_from(">I", content, 94)[0]
    path.write_bytes(content)
    original = Path.open
    reads = []

    class ObservedFile:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def seek(self, *args):
            return self.source.seek(*args)

        def read(self, size=-1):
            start = self.source.tell()
            assert size >= 0
            assert start + size <= body_start or start >= body_end
            data = self.source.read(size)
            reads.append(len(data))
            return data

    monkeypatch.setattr(
        Path,
        "open",
        lambda self, *a, **kw: (
            ObservedFile(original(self, *a, **kw))
            if self == path
            else original(self, *a, **kw)
        ),
    )
    result = inspect_reflowable_book(path, "MOBI")
    assert result.title == "放学后"
    assert result.cover.content == b"\xff\xd8\xff\xe0synthetic-cover"
    assert sum(reads) < 2048
