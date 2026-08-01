from pathlib import Path

from app.modules.imports.application.import_pdf import parse_pdf_metadata


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

    metadata = parse_pdf_metadata(pdf_path, "怪物大师10冰封的时之轮.pdf")

    assert metadata["title"] == "怪物大师10冰封的时之轮"
    assert metadata["author"] == "雷欧幻象"
    assert metadata["tags"] == ["接力出版社"]
    assert metadata["embeddedTitle"] is None
    assert metadata["rawMetadata"]["Title"] == "封面"
    assert metadata["rawMetadata"]["Author"] == "雷欧幻象"
    assert metadata["rawMetadata"]["Keywords"] == "接力出版社"
    assert "�" not in "".join(
        str(metadata["rawMetadata"].get(field) or "")
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

    metadata = parse_pdf_metadata(pdf_path, "怪物大师10冰封的时之轮.pdf")

    assert metadata["title"] == "怪物大师10冰封的时之轮"
    assert metadata["author"] == "雷欧幻象"
    assert metadata["tags"] == ["fiction"]
    assert metadata["embeddedTitle"] is None
