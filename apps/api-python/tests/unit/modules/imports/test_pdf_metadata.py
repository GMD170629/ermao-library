from pathlib import Path

from app.modules.imports.domain.pdf_content import PdfContentKind
from app.modules.imports.infrastructure.pdf_inspection import inspect_pdf


def _write_pdf_with_literal_metadata(
    path: Path,
    *,
    title: bytes,
    author: bytes,
    keywords: bytes,
) -> None:
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >> endobj\n"
        b"4 0 obj << /Title ("
        + title
        + b") /Author ("
        + author
        + b") /Keywords ("
        + keywords
        + b") >> endobj\n"
        b"trailer << /Root 1 0 R /Info 4 0 R >>\n%%EOF\n"
    )


def test_pdf_metadata_decodes_utf16_and_rejects_a_generic_title(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "source.pdf"
    _write_pdf_with_literal_metadata(
        pdf_path,
        title=bytes.fromhex("feff5c5c019762"),
        author=b"\xfe\xff" + "雷欧幻象".encode("utf-16-be"),
        keywords=b"\xfe\xff" + "接力出版社".encode("utf-16-be"),
    )

    metadata = inspect_pdf(pdf_path, "怪物大师10冰封的时之轮.pdf")

    assert metadata.title == "怪物大师10冰封的时之轮"
    assert metadata.author == "雷欧幻象"
    assert metadata.tags == ("接力出版社",)
    assert metadata.embedded_title is None
    assert metadata.raw_metadata["Title"] == "封面"
    assert metadata.raw_metadata["Author"] == "雷欧幻象"
    assert metadata.raw_metadata["Keywords"] == "接力出版社"
    assert metadata.content_kind is PdfContentKind.IMAGE_ONLY
    assert "�" not in "".join(
        str(metadata.raw_metadata.get(field) or "")
        for field in ("Title", "Author", "Subject", "Keywords")
    )


def test_pdf_metadata_rejects_truncated_utf16_and_decodes_octal_escapes(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "source.pdf"
    encoded_author = b"\xfe\xff" + "雷欧幻象".encode("utf-16-be")
    octal_author = b"".join(f"\\{byte:03o}".encode("ascii") for byte in encoded_author)
    _write_pdf_with_literal_metadata(
        pdf_path,
        title=bytes.fromhex("feff4e"),
        author=octal_author,
        keywords=b"fiction",
    )

    metadata = inspect_pdf(pdf_path, "怪物大师10冰封的时之轮.pdf")

    assert metadata.title == "怪物大师10冰封的时之轮"
    assert metadata.author == "雷欧幻象"
    assert metadata.tags == ("fiction",)
    assert metadata.embedded_title is None


def test_pdf_inspection_timeout_is_unknown(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    _write_pdf_with_literal_metadata(
        pdf_path,
        title=b"manual",
        author=b"author",
        keywords=b"fiction",
    )
    ticks = iter((0.0, 4.0, 4.0, 4.0, 4.0))

    metadata = inspect_pdf(pdf_path, clock=lambda: next(ticks))

    assert metadata.content_kind is PdfContentKind.UNKNOWN
    assert metadata.text_evidence.reason == "timeout"


def test_invalid_pdf_inspection_is_unknown(tmp_path: Path) -> None:
    pdf_path = tmp_path / "invalid.pdf"
    pdf_path.write_bytes(b"not a PDF")

    metadata = inspect_pdf(pdf_path)

    assert metadata.content_kind is PdfContentKind.UNKNOWN
    assert metadata.text_evidence.reason == "inspection-error"


def test_large_image_only_pdf_scans_each_page_without_rendering(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    pdf_path = tmp_path / "large-image-only.pdf"
    document = pdfium.PdfDocument.new()
    for _ in range(500):
        page = document.new_page(595, 842)
        page.close()
    document.save(pdf_path)
    document.close()

    metadata = inspect_pdf(pdf_path, clock=lambda: 0.0)

    assert metadata.content_kind is PdfContentKind.IMAGE_ONLY
    assert metadata.text_evidence.inspected_pages == 500
    assert metadata.text_evidence.maximum_effective_characters == 0
