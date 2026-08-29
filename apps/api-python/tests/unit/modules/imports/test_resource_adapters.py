from __future__ import annotations

import pytest

from app.modules.imports.application.audio_types import SUPPORTED_AUDIO_EXTS
from app.modules.imports.application.readable_resource.ports import adapter_identity
from app.modules.imports.domain.resource_adapters import (
    ResourceAdapterId,
    match_directory_adapters_for_samples,
    match_file_adapters,
    source_format_for_filename,
    unique_adapter_or_none,
)


@pytest.mark.parametrize(
    ("filename", "adapter_id"),
    (
        ("Novel.epub", ResourceAdapterId.EPUB),
        ("scan.PDF", ResourceAdapterId.PDF),
        ("notes.txt", ResourceAdapterId.TXT),
        ("legacy.fb2", ResourceAdapterId.TXT),
        ("book.mobi", ResourceAdapterId.MOBI_FAMILY),
        ("book.azw3", ResourceAdapterId.MOBI_FAMILY),
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


@pytest.mark.parametrize("extension", sorted(SUPPORTED_AUDIO_EXTS))
def test_every_declared_audio_extension_has_file_and_directory_adapters(
    extension: str,
) -> None:
    file_adapter = unique_adapter_or_none(match_file_adapters(f"chapter{extension}"))
    directory_adapter = unique_adapter_or_none(
        match_directory_adapters_for_samples((f"01{extension}",))
    )

    assert file_adapter is not None
    assert file_adapter.adapter_id is ResourceAdapterId.AUDIO_FILE
    assert directory_adapter is not None
    assert directory_adapter.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY


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


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    (
        ("issue.cbz", "CBZ"),
        ("issue.cbr", "CBR"),
        ("issue.zip", "ZIP"),
        ("issue.rar", "RAR"),
    ),
)
def test_comic_archive_source_format_is_concrete(
    filename: str, expected_format: str
) -> None:
    adapter = unique_adapter_or_none(match_file_adapters(filename))
    assert adapter is not None
    assert adapter.adapter_id is ResourceAdapterId.COMIC_ARCHIVE
    assert source_format_for_filename(adapter, filename) == expected_format


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    (("notes.txt", "TXT"), ("book.fb2", "FB2")),
)
def test_text_adapter_preserves_the_concrete_source_format(
    filename: str,
    expected_format: str,
) -> None:
    adapter = unique_adapter_or_none(match_file_adapters(filename))
    assert adapter is not None
    assert adapter.adapter_id is ResourceAdapterId.TXT
    assert source_format_for_filename(adapter, filename) == expected_format


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    (
        ("book.mobi", "MOBI"),
        ("book.azw", "AZW"),
        ("book.azw3", "AZW3"),
        ("book.prc", "PRC"),
    ),
)
def test_mobi_family_adapter_persists_the_concrete_source_format(
    filename: str,
    expected_format: str,
) -> None:
    adapter = unique_adapter_or_none(match_file_adapters(filename))
    assert adapter is not None
    identity = adapter_identity(adapter, source_name=filename)
    assert identity.adapter_id == ResourceAdapterId.MOBI_FAMILY.value
    assert identity.adapter_version == "2"
    assert identity.format_label == expected_format


@pytest.mark.parametrize(
    ("filename", "expected_format"),
    (
        ("issue.cbz", "CBZ"),
        ("issue.cbr", "CBR"),
        ("issue.zip", "ZIP"),
        ("issue.rar", "RAR"),
    ),
)
def test_adapter_identity_persists_concrete_comic_format(
    filename: str, expected_format: str
) -> None:
    adapter = unique_adapter_or_none(match_file_adapters(filename))
    assert adapter is not None
    identity = adapter_identity(adapter, source_name=filename)
    assert identity.adapter_id == ResourceAdapterId.COMIC_ARCHIVE.value
    assert identity.format_label == expected_format
