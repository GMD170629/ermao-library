from __future__ import annotations

import pytest

from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterId,
    match_directory_adapters_for_samples,
    match_file_adapters,
    unique_adapter_or_none,
)


@pytest.mark.parametrize(
    ("filename", "adapter_id"),
    (
        ("Novel.epub", ResourceAdapterId.EPUB),
        ("scan.PDF", ResourceAdapterId.PDF),
        ("notes.txt", ResourceAdapterId.TXT),
        ("legacy.fb2", ResourceAdapterId.TXT),
        ("book.mobi", ResourceAdapterId.KINDLE),
        ("book.azw3", ResourceAdapterId.KINDLE),
        ("issue.cbz", ResourceAdapterId.COMIC_ARCHIVE),
        ("pack.zip", ResourceAdapterId.COMIC_ARCHIVE),
        ("chapter.mp3", ResourceAdapterId.AUDIO_FILE),
        ("chapter.m4b", ResourceAdapterId.AUDIO_FILE),
    ),
)
def test_file_adapter_match(
    filename: str,
    adapter_id: ResourceAdapterId,
) -> None:
    matches = match_file_adapters(filename)
    adapter = unique_adapter_or_none(matches)
    assert adapter is not None
    assert adapter.adapter_id is adapter_id
    assert adapter.is_directory_adapter is False


@pytest.mark.parametrize(
    ("samples", "adapter_id"),
    (
        (("01.mp3", "02.flac"), ResourceAdapterId.AUDIOBOOK_DIRECTORY),
        (("page-001.png", "page-002.jpg"), ResourceAdapterId.IMAGE_DIRECTORY),
        (("cover.webp",), ResourceAdapterId.IMAGE_DIRECTORY),
        (("track.m4b",), ResourceAdapterId.AUDIOBOOK_DIRECTORY),
    ),
)
def test_directory_adapter_match(
    samples: tuple[str, ...],
    adapter_id: ResourceAdapterId,
) -> None:
    matches = match_directory_adapters_for_samples(samples)
    adapter = unique_adapter_or_none(matches)
    assert adapter is not None
    assert adapter.adapter_id is adapter_id
    assert adapter.is_directory_adapter is True


def test_file_adapter_does_not_match_directory_only_extensions_as_directory() -> None:
    assert match_file_adapters("folder") == ()
    assert unique_adapter_or_none(match_file_adapters("readme.md")) is None


def test_directory_samples_require_all_names_compatible() -> None:
    assert match_directory_adapters_for_samples(("a.mp3", "b.png")) == ()
    assert match_directory_adapters_for_samples(()) == ()


def test_unique_adapter_or_none_rejects_empty_and_ambiguous() -> None:
    assert unique_adapter_or_none(()) is None
    epub = match_file_adapters("a.epub")
    pdf = match_file_adapters("a.pdf")
    assert unique_adapter_or_none(epub + pdf) is None
