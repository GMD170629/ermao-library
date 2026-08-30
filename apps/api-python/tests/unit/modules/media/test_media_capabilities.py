from __future__ import annotations

import pytest

from app.contracts.media_capabilities import (
    canonical_publication_mime_type,
    capability_for_format,
    resolve_asset_mime_type,
)
from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_FORMATS,
    ReaderSafetyDeliveryMode,
    ReaderSafetyFormat,
)


@pytest.mark.parametrize(
    ("source_format", "expected"),
    [
        ("EPUB", "application/epub+zip"),
        ("MOBI", "application/x-mobipocket-ebook"),
        ("AZW", "application/vnd.amazon.ebook"),
        ("AZW3", "application/vnd.amazon.ebook"),
        ("PRC", "application/x-mobipocket-ebook"),
        ("FB2", "application/x-fictionbook+xml"),
        ("TXT", "text/plain"),
        ("PDF", "application/pdf"),
        ("CBZ", "application/vnd.comicbook+zip"),
        ("ZIP", "application/zip"),
        ("CBR", "application/vnd.comicbook-rar"),
        ("RAR", "application/vnd.rar"),
    ],
)
def test_canonical_publication_mime_type(
    source_format: str,
    expected: str,
) -> None:
    assert canonical_publication_mime_type(source_format) == expected


def test_image_directory_has_no_synthetic_publication_mime_type() -> None:
    assert canonical_publication_mime_type("IMAGE_DIR") is None


@pytest.mark.parametrize(
    ("source_format", "filename", "expected"),
    [
        ("AZW", "book.azw", "application/vnd.amazon.ebook"),
        ("AZW3", "book.azw3", "application/vnd.amazon.ebook"),
        ("MOBI", "book.mobi", "application/x-mobipocket-ebook"),
        ("PRC", "book.prc", "application/x-mobipocket-ebook"),
    ],
)
def test_mobi_family_actual_format_uses_canonical_mime(
    source_format: str,
    filename: str,
    expected: str,
) -> None:
    assert (
        resolve_asset_mime_type(
            resource_format=source_format,
            asset_role="PRIMARY",
            filename=filename,
            stored_mime_type="application/octet-stream",
        )
        == expected
    )


def test_generic_kindle_format_is_unsupported() -> None:
    assert capability_for_format("KINDLE") is None
    assert canonical_publication_mime_type("KINDLE") is None
    assert all(policy.id.value != "KINDLE" for policy in READER_SAFETY_FORMATS.values())


def test_generated_delivery_contract_distinguishes_reader_morphologies() -> None:
    for source_format in (
        ReaderSafetyFormat.EPUB,
        ReaderSafetyFormat.FB2,
        ReaderSafetyFormat.TXT,
        ReaderSafetyFormat.MOBI,
        ReaderSafetyFormat.AZW,
        ReaderSafetyFormat.AZW3,
        ReaderSafetyFormat.PRC,
    ):
        assert (
            READER_SAFETY_FORMATS[source_format].delivery_mode
            is ReaderSafetyDeliveryMode.DOWNLOAD_ORIGINAL
        )
    for source_format in (
        ReaderSafetyFormat.PDF,
        ReaderSafetyFormat.CBZ,
        ReaderSafetyFormat.ZIP,
        ReaderSafetyFormat.CBR,
        ReaderSafetyFormat.RAR,
        ReaderSafetyFormat.IMAGE_DIR,
    ):
        assert (
            READER_SAFETY_FORMATS[source_format].delivery_mode
            is ReaderSafetyDeliveryMode.STREAM
        )


@pytest.mark.parametrize("stored", [None, "", "application/octet-stream"])
def test_primary_asset_replaces_missing_or_generic_mime(stored: str | None) -> None:
    assert (
        resolve_asset_mime_type(
            resource_format="EPUB",
            asset_role="PRIMARY",
            filename="book.epub",
            stored_mime_type=stored,
        )
        == "application/epub+zip"
    )


def test_canonical_publication_mime_replaces_conflicting_stored_mime() -> None:
    assert (
        resolve_asset_mime_type(
            resource_format="AZW3",
            asset_role="PRIMARY",
            filename="book.azw3",
            stored_mime_type="application/x-mobipocket-ebook; charset=binary",
        )
        == "application/vnd.amazon.ebook"
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("001.JPG", "image/jpeg"), ("002.png", "image/png"), ("003.webp", "image/webp")],
)
def test_image_directory_page_mime_comes_from_original_page(
    filename: str,
    expected: str,
) -> None:
    assert (
        resolve_asset_mime_type(
            resource_format="IMAGE_DIR",
            asset_role="PAGE",
            filename=filename,
            stored_mime_type=None,
        )
        == expected
    )


def test_comic_page_rejects_mime_outside_generated_allowlist() -> None:
    assert (
        resolve_asset_mime_type(
            resource_format="IMAGE_DIR",
            asset_role="PAGE",
            filename="page.avif",
            stored_mime_type="image/avif",
        )
        == "application/octet-stream"
    )
