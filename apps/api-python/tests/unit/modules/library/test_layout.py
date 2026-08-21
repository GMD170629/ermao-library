from __future__ import annotations

import unicodedata

import pytest

from app.modules.library.domain.layout import (
    LayoutViolationCode,
    LibraryOrganizationMode,
    is_audiobook_disc_directory,
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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "book.mp3",
            ("book:book.mp3", "book", "resource:book.mp3", "book", "book.mp3", 0),
        ),
        (
            "Book/CD1/01.mp3",
            ("book:Book", "Book", "resource:Book", "Book", "Book/CD1/01.mp3", 0),
        ),
        (
            "Book/V1/CD1/01.mp3",
            ("book:Book", "Book", "resource:Book/V1", "V1", "Book/V1/CD1/01.mp3", 0),
        ),
        (
            "Book/V1/Vol1/CD2/01.mp3",
            (
                "book:Book",
                "Book",
                "resource:Book/V1/Vol1",
                "Vol1",
                "Book/V1/Vol1/CD2/01.mp3",
                0,
            ),
        ),
        (
            "Book/Disc 1/V1/Disk-02/Vol1/盘3/Extra/01.mp3",
            (
                "book:Book",
                "Book",
                "resource:Book/V1/Vol1/Extra",
                "Extra",
                "Book/Disc 1/V1/Disk-02/Vol1/盘3/Extra/01.mp3",
                0,
            ),
        ),
    ],
)
def test_audiobook_uses_resource_positions_after_transparent_disc_directories(
    path: str, expected: tuple[str, str, str, str, str, int]
) -> None:
    assert _topology(LibraryOrganizationMode.AUDIOBOOK, path) == expected


@pytest.mark.parametrize(
    "name",
    ["CD", "cd1", "CD 2", "Disc-03", "disk_4", "碟", "碟1", "盘 2"],
)
def test_disc_directory_variants_are_transparent(name: str) -> None:
    assert is_audiobook_disc_directory(name)


def test_multiple_audio_assets_replay_the_same_resource_identity() -> None:
    first = _topology(LibraryOrganizationMode.AUDIOBOOK, "Book/V1/Vol1/CD1/01.mp3")
    second = _topology(LibraryOrganizationMode.AUDIOBOOK, "Book/V1/Vol1/CD2/99.mp3")

    assert first[:4] == second[:4]
    assert first[2] == "resource:Book/V1/Vol1"
    assert first[4] == "Book/V1/Vol1/CD1/01.mp3"
    assert second[4] == "Book/V1/Vol1/CD2/99.mp3"


def test_same_path_is_independent_of_other_inputs_and_order() -> None:
    target = "Book/V1/Vol1/CD1/01.mp3"
    expected = parse_library_file_path(target, LibraryOrganizationMode.AUDIOBOOK)
    paths = ["Other/V2/02.mp3", target, "Book/V1/Vol2/03.mp3"]

    first = [
        parse_library_file_path(path, LibraryOrganizationMode.AUDIOBOOK)
        for path in paths
    ][1]
    second = [
        parse_library_file_path(path, LibraryOrganizationMode.AUDIOBOOK)
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
