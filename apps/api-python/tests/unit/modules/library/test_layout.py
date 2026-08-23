from __future__ import annotations

import unicodedata

import pytest

from app.modules.library.domain.layout import (
    LayoutViolationCode,
    LibraryOrganizationMode,
    parse_library_file_path,
)


def _topology(
    mode: LibraryOrganizationMode, path: str
) -> tuple[str, str, str, str, str, int]:
    result = parse_library_file_path(path, mode)
    assert result.violations == ()
    assert result.book is not None
    book = result.book
    resource = book.resources[0]
    asset = resource.assets[0]
    return (
        book.source_key,
        book.source_name,
        resource.source_key,
        resource.source_name,
        asset.relative_path,
        asset.order,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "A/B/book.epub",
            (
                "book:A/B/book.epub",
                "book",
                "resource:A/B/book.epub",
                "book",
                "A/B/book.epub",
                0,
            ),
        ),
        (
            "十/级/以/上/目录/作品.pdf",
            (
                "book:十/级/以/上/目录/作品.pdf",
                "作品",
                "resource:十/级/以/上/目录/作品.pdf",
                "作品",
                "十/级/以/上/目录/作品.pdf",
                0,
            ),
        ),
    ],
)
def test_flat_maps_every_resource_to_an_independent_book(
    path: str, expected: tuple[str, str, str, str, str, int]
) -> None:
    assert _topology(LibraryOrganizationMode.FLAT, path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "book.epub",
            ("book:book.epub", "book", "resource:book.epub", "book", "book.epub", 0),
        ),
        (
            "三体/01.epub",
            ("book:三体", "三体", "resource:三体/01.epub", "01", "三体/01.epub", 0),
        ),
        (
            "三体/中文版/精校/01.epub",
            (
                "book:三体",
                "三体",
                "resource:三体/中文版/精校/01.epub",
                "01",
                "三体/中文版/精校/01.epub",
                0,
            ),
        ),
    ],
)
def test_volumes_anchors_book_and_resource_from_the_source_path(
    path: str, expected: tuple[str, str, str, str, str, int]
) -> None:
    assert _topology(LibraryOrganizationMode.VOLUMES, path) == expected


def test_same_path_is_independent_of_other_inputs_and_order() -> None:
    target = "Book/Edition/01.epub"
    expected = parse_library_file_path(target, LibraryOrganizationMode.VOLUMES)
    paths = ["Other/02.epub", target, "Book/03.epub"]

    first = [
        parse_library_file_path(path, LibraryOrganizationMode.VOLUMES) for path in paths
    ][1]
    second = [
        parse_library_file_path(path, LibraryOrganizationMode.VOLUMES)
        for path in reversed(paths)
    ][1]

    assert first == expected
    assert second == expected


def test_backslashes_are_normalized() -> None:
    result = parse_library_file_path(
        "三体\\中文版\\精校\\01.epub", LibraryOrganizationMode.VOLUMES
    )

    assert result.book is not None
    assert result.book.source_key == "book:三体"
    assert result.book.resources[0].source_key == "resource:三体/中文版/精校/01.epub"
    assert result.book.resources[0].assets[0].relative_path == (
        "三体/中文版/精校/01.epub"
    )


def test_nfc_spelling_produces_the_same_topology_keys() -> None:
    nfd_path = unicodedata.normalize("NFD", "café/中文版/01.epub")
    nfc_path = unicodedata.normalize("NFC", "café/中文版/01.epub")

    nfd = parse_library_file_path(nfd_path, LibraryOrganizationMode.VOLUMES)
    nfc = parse_library_file_path(nfc_path, LibraryOrganizationMode.VOLUMES)

    assert nfd.book is not None and nfc.book is not None
    assert nfd.book.source_key == nfc.book.source_key == "book:café"
    assert nfd.book.resources[0].source_key == nfc.book.resources[0].source_key
    assert nfd.book.resources[0].assets[0].relative_path == nfd_path
    assert nfc.book.resources[0].assets[0].relative_path == nfc_path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/tmp/book.epub",
        "C:/library/book.epub",
        "../book.epub",
        "a/./b.epub",
        "a//b.epub",
        "book.epub/",
    ],
)
def test_invalid_relative_paths_return_one_stable_violation(path: str) -> None:
    result = parse_library_file_path(path, LibraryOrganizationMode.FLAT)

    assert result.book is None
    assert len(result.violations) == 1
    assert result.violations[0].code is LayoutViolationCode.INVALID_RELATIVE_PATH
    assert result.violations[0].relative_path == path
