import zlib
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, EncodedStreamObject, NameObject

from app.infrastructure.bounded_inspection import LimitedReader
from app.infrastructure.pdf_embedded_metadata import XMP_BYTES_LIMIT
from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)


def _xmp(body: str) -> bytes:
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:pdf="http://ns.adobe.com/pdf/1.3/">'
        f'<rdf:RDF><rdf:Description rdf:about="">{body}</rdf:Description>'
        '</rdf:RDF></x:xmpmeta>'
    ).encode()


def test_pdf_metadata_and_navigation_without_page_payload(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "book.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(200, 200)
    payload = DecodedStreamObject()
    payload.set_data(b"body must not be inspected " * 200_000)
    page[NameObject("/Contents")] = writer._add_object(payload)
    writer.add_metadata(
        {"/Title": "封面", "/Author": "雷欧幻象", "/Keywords": "fiction/故事\\冒险-旅行"}
    )
    writer.add_outline_item("第一章", 0)
    writer.write(path)
    reads = []
    original = LimitedReader.read

    def observe(self, size=-1):
        start = self.tell()
        data = original(self, size)
        reads.append((start, self.tell()))
        return data

    monkeypatch.setattr(LimitedReader, "read", observe)
    result = inspect_pdf(path)
    assert result.title == "book"
    assert result.embedded_metadata.authors == ("雷欧幻象",)
    assert result.embedded_metadata.subjects == ("fiction", "故事", "冒险", "旅行")
    assert result.page_count == 1
    assert result.chapters[0].page_number == 1
    assert sum(end - start for start, end in reads) < 100_000
    assert not any(start <= path.stat().st_size // 2 < end for start, end in reads)


def test_aes128_pdf_with_empty_password_reads_metadata_and_navigation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "encrypted.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_blank_page(200, 200)
    writer.add_metadata(
        {"/Title": "加密报告", "/Author": "测试作者", "/Keywords": "report,报告"}
    )
    writer.add_outline_item("第二章", 1)
    writer.encrypt("", owner_password="owner-password", algorithm="AES-128")
    writer.write(path)
    original_bytes = path.read_bytes()

    result = inspect_pdf(path)

    assert result.embedded_metadata.title == "加密报告"
    assert result.embedded_metadata.authors == ("测试作者",)
    assert result.embedded_metadata.subjects == ("report", "报告")
    assert result.page_count == 2
    assert len(result.chapters) == 1
    assert result.chapters[0].title == "第二章"
    assert result.chapters[0].page_number == 2
    assert result.text_evidence.inspected_pages == 0
    assert path.read_bytes() == original_bytes


def test_invalid_pdf_does_not_repair_or_invent_page_count(tmp_path: Path) -> None:
    path = tmp_path / "invalid.pdf"
    path.write_bytes(b"%PDF-1.4\n/Type /Page\n" + b"x" * 100_000)
    result = inspect_pdf(path)
    assert result.page_count is None
    assert result.chapters == ()


def test_large_pdf_counts_pages_without_text_inspection(tmp_path: Path) -> None:
    path = tmp_path / "large.pdf"
    writer = PdfWriter()
    for _ in range(500):
        writer.add_blank_page(200, 200)
    writer.write(path)
    result = inspect_pdf(path)
    assert result.page_count == 500
    assert result.text_evidence.inspected_pages == 0


def test_pdf_xmp_standard_fields_override_info_by_field(tmp_path: Path) -> None:
    path = tmp_path / "merged.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_metadata({
        "/Title": "Info 标题", "/Author": "Info 作者",
        "/Subject": "Info 简介", "/Keywords": "Info 类别,第二类",
    })
    writer.xmp_metadata = _xmp(
        '<dc:title><rdf:Alt><rdf:li xml:lang="en-US">English</rdf:li>'
        '<rdf:li xml:lang="x-default">XMP 标题</rdf:li></rdf:Alt></dc:title>'
        '<dc:creator><rdf:Seq><rdf:li>作者甲</rdf:li><rdf:li>作者乙</rdf:li>'
        '</rdf:Seq></dc:creator>'
        '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">XMP 简介'
        '</rdf:li></rdf:Alt></dc:description>'
        '<dc:subject><rdf:Bag><rdf:li>儿童文学/奇幻/冒险</rdf:li><rdf:li>成长\\勇气－团队–合作'
        '</rdf:li></rdf:Bag></dc:subject>'
        '<dc:language><rdf:Bag><rdf:li>zh-CN</rdf:li></rdf:Bag></dc:language>'
        '<dc:publisher><rdf:Bag><rdf:li>接力出版社</rdf:li></rdf:Bag></dc:publisher>'
        '<dc:date><rdf:Seq><rdf:li>invalid</rdf:li><rdf:li>2012</rdf:li>'
        '</rdf:Seq></dc:date>'
        '<dc:identifier><rdf:Bag><rdf:li>urn:isbn:9781234567890</rdf:li>'
        '</rdf:Bag></dc:identifier>'
    )
    writer.write(path)

    result = inspect_pdf(path)
    metadata = result.embedded_metadata
    assert metadata.title == "XMP 标题"
    assert metadata.authors == ("作者甲", "作者乙")
    assert metadata.description == "XMP 简介"
    assert metadata.subjects == ("儿童文学", "奇幻", "冒险", "成长", "勇气", "团队", "合作")
    assert metadata.language == "zh-CN"
    assert metadata.publisher == "接力出版社"
    assert metadata.published_at == "2012"
    assert metadata.identifier == "urn:isbn:9781234567890"
    assert metadata.isbn == "9781234567890"
    assert result.page_count == 1
    candidate = RegistryResourceAdapterExecutor().inspect_embedded_local_metadata(
        path, "PDF"
    )
    assert candidate is not None
    assert candidate.metadata == metadata


@pytest.mark.parametrize("compressed", [False, True])
def test_pdf_xmp_only_uses_pdf_author_and_info_fills_missing_fields(
    tmp_path: Path, compressed: bool,
) -> None:
    path = tmp_path / "partial.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_metadata({"/Subject": "Info 简介", "/Keywords": "甲;乙"})
    xmp = _xmp(
        '<dc:title><rdf:Alt><rdf:li xml:lang="en-US">Only title'
        '</rdf:li></rdf:Alt></dc:title><pdf:Author>XMP 作者</pdf:Author>'
        '<dc:description><rdf:Alt><rdf:li xml:lang="x-default">   '
        '</rdf:li></rdf:Alt></dc:description>'
    )
    if compressed:
        stream = EncodedStreamObject()
        stream._data = zlib.compress(xmp)
        stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        writer.root_object[NameObject("/Metadata")] = writer._add_object(stream)
    else:
        writer.xmp_metadata = xmp
    writer.write(path)

    metadata = inspect_pdf(path).embedded_metadata
    assert metadata.title == "Only title"
    assert metadata.authors == ("XMP 作者",)
    assert metadata.description == "Info 简介"
    assert metadata.subjects == ("甲", "乙")


@pytest.mark.parametrize("mode", ["malformed", "encoded_limit", "decoded_limit"])
def test_bad_xmp_falls_back_to_info(tmp_path: Path, mode: str) -> None:
    path = tmp_path / "bad-xmp.pdf"
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.add_metadata({"/Title": "Info 标题", "/Author": "Info 作者"})
    if mode == "malformed":
        writer.xmp_metadata = b"<rdf:RDF>"
    elif mode == "encoded_limit":
        writer.xmp_metadata = b"x" * (XMP_BYTES_LIMIT + 1)
    else:
        stream = EncodedStreamObject()
        stream._data = zlib.compress(b"x" * (XMP_BYTES_LIMIT + 1))
        stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        writer.root_object[NameObject("/Metadata")] = writer._add_object(stream)
    writer.write(path)
    original = path.read_bytes()

    result = inspect_pdf(path)
    assert result.embedded_metadata.title == "Info 标题"
    assert result.embedded_metadata.authors == ("Info 作者",)
    assert result.page_count == 1
    assert path.read_bytes() == original
