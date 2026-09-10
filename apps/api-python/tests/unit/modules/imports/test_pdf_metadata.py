from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from app.modules.imports.infrastructure.limited_read import LimitedReader
from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf


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
        {"/Title": "封面", "/Author": "雷欧幻象", "/Keywords": "fiction,故事"}
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
    assert result.embedded_author == "雷欧幻象"
    assert result.tags == ("fiction", "故事")
    assert result.page_count == 1
    assert result.chapters[0].page_number == 1
    assert sum(end - start for start, end in reads) < 100_000
    assert not any(start <= path.stat().st_size // 2 < end for start, end in reads)


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
