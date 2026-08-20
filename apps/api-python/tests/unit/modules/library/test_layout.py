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
) -> tuple[str, str, str | None, str, str, str]:
    result = parse_library_file_path(path, mode)
    assert result.violations == ()
    assert result.work is not None
    work = result.work
    version = work.versions[0]
    volume = version.volumes[0]
    return (
        work.source_key,
        work.source_name,
        version.source_name,
        version.source_key,
        volume.source_name,
        volume.source_key,
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "A/B/book.epub",
            (
                "work:A/B/book.epub",
                "book",
                None,
                "version:A/B/book.epub",
                "book",
                "volume:A/B/book.epub",
            ),
        ),
        (
            "十/级/以/上/目录/作品.pdf",
            (
                "work:十/级/以/上/目录/作品.pdf",
                "作品",
                None,
                "version:十/级/以/上/目录/作品.pdf",
                "作品",
                "volume:十/级/以/上/目录/作品.pdf",
            ),
        ),
    ],
)
def test_flat_maps_every_file_to_an_independent_work(
    path: str, expected: tuple[str, str, str | None, str, str, str]
) -> None:
    assert _topology(LibraryOrganizationMode.FLAT, path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "book.epub",
            (
                "work:book.epub",
                "book",
                None,
                "version:book.epub",
                "book",
                "volume:book.epub",
            ),
        ),
        (
            "三体/01.epub",
            (
                "work:三体",
                "三体",
                None,
                "version:三体",
                "01",
                "volume:三体/01.epub",
            ),
        ),
        (
            "三体/中文版/精校/01.epub",
            (
                "work:三体",
                "三体",
                "中文版",
                "version:三体/中文版",
                "01",
                "volume:三体/中文版/精校/01.epub",
            ),
        ),
    ],
)
def test_volumes_uses_only_fixed_work_and_version_positions(
    path: str, expected: tuple[str, str, str | None, str, str, str]
) -> None:
    assert _topology(LibraryOrganizationMode.VOLUMES, path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            "book.mp3",
            (
                "work:book.mp3",
                "book",
                None,
                "version:book.mp3",
                "book",
                "volume:book.mp3",
            ),
        ),
        (
            "Book/CD1/01.mp3",
            (
                "work:Book",
                "Book",
                None,
                "version:Book",
                "Book",
                "volume:Book",
            ),
        ),
        (
            "Book/V1/CD1/01.mp3",
            (
                "work:Book",
                "Book",
                "V1",
                "version:Book/V1",
                "V1",
                "volume:Book/V1",
            ),
        ),
        (
            "Book/V1/Vol1/CD2/01.mp3",
            (
                "work:Book",
                "Book",
                "V1",
                "version:Book/V1",
                "Vol1",
                "volume:Book/V1/Vol1",
            ),
        ),
        (
            "Book/Disc 1/V1/Disk-02/Vol1/盘3/Extra/01.mp3",
            (
                "work:Book",
                "Book",
                "V1",
                "version:Book/V1",
                "Vol1",
                "volume:Book/V1/Vol1",
            ),
        ),
    ],
)
def test_audiobook_uses_fixed_positions_after_transparent_disc_directories(
    path: str, expected: tuple[str, str, str | None, str, str, str]
) -> None:
    assert _topology(LibraryOrganizationMode.AUDIOBOOK, path) == expected


@pytest.mark.parametrize(
    "name",
    ["CD", "cd1", "CD 2", "Disc-03", "disk_4", "碟", "碟1", "盘 2"],
)
def test_disc_directory_variants_are_transparent(name: str) -> None:
    assert is_audiobook_disc_directory(name)


def test_multiple_audio_files_replay_the_same_volume_identity() -> None:
    first = _topology(LibraryOrganizationMode.AUDIOBOOK, "Book/V1/Vol1/CD1/01.mp3")
    second = _topology(LibraryOrganizationMode.AUDIOBOOK, "Book/V1/Vol1/CD2/99.mp3")

    assert first[:5] == second[:5]
    assert first[5] == second[5] == "volume:Book/V1/Vol1"


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

    assert result.work is not None
    assert result.work.source_key == "work:三体"
    assert result.work.versions[0].source_key == "version:三体/中文版"
    assert result.work.versions[0].volumes[0].source_key == (
        "volume:三体/中文版/精校/01.epub"
    )
    assert result.work.versions[0].volumes[0].assets[0].relative_path == (
        "三体/中文版/精校/01.epub"
    )


def test_nfc_spelling_produces_the_same_topology_keys() -> None:
    nfd_path = unicodedata.normalize("NFD", "café/中文版/01.epub")
    nfc_path = unicodedata.normalize("NFC", "café/中文版/01.epub")

    nfd = parse_library_file_path(nfd_path, LibraryOrganizationMode.VOLUMES)
    nfc = parse_library_file_path(nfc_path, LibraryOrganizationMode.VOLUMES)

    assert nfd.work is not None and nfc.work is not None
    assert nfd.work.source_key == nfc.work.source_key == "work:café"
    assert nfd.work.versions[0].source_key == nfc.work.versions[0].source_key
    assert (
        nfd.work.versions[0].volumes[0].source_key
        == nfc.work.versions[0].volumes[0].source_key
    )


@pytest.mark.parametrize(
    "path",
    ["", "/tmp/book.epub", "C:/library/book.epub", "../book.epub", "a/./b.epub", "a//b.epub", "book.epub/"],
)
def test_invalid_relative_paths_return_one_stable_violation(path: str) -> None:
    result = parse_library_file_path(path, LibraryOrganizationMode.FLAT)

    assert result.work is None
    assert len(result.violations) == 1
    assert result.violations[0].code is LayoutViolationCode.INVALID_RELATIVE_PATH
    assert result.violations[0].relative_path == path
