from __future__ import annotations

import pytest

from app.contracts.media_capabilities import (
    canonical_publication_mime_type,
    exact_source_format,
    resolve_asset_mime_type,
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
    ("filename", "expected"),
    [
        ("book.mobi", "MOBI"),
        ("book.azw", "AZW"),
        ("book.AZW3", "AZW3"),
        ("book.prc", "PRC"),
    ],
)
def test_kindle_catalog_family_recovers_exact_original_format(
    filename: str,
    expected: str,
) -> None:
    assert exact_source_format(resource_format="KINDLE", filename=filename) == expected


def test_exact_source_format_preserves_non_kindle_resource_format() -> None:
    assert (
        exact_source_format(resource_format="IMAGE_DIR", filename="001.png")
        == "IMAGE_DIR"
    )


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("book.azw", "application/vnd.amazon.ebook"),
        ("book.azw3", "application/vnd.amazon.ebook"),
        ("book.mobi", "application/x-mobipocket-ebook"),
        ("book.prc", "application/x-mobipocket-ebook"),
    ],
)
def test_kindle_catalog_family_uses_exact_original_mime(
    filename: str,
    expected: str,
) -> None:
    assert (
        resolve_asset_mime_type(
            resource_format="KINDLE",
            asset_role="PRIMARY",
            filename=filename,
            stored_mime_type="application/octet-stream",
        )
        == expected
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
