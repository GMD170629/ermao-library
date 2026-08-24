from __future__ import annotations

import pytest

from app.modules.imports.domain.ignore_rules import (
    is_builtin_ignored_file,
    matches_configured_ignore_patterns,
    should_ignore_source_entry,
)


@pytest.mark.parametrize(
    "name",
    [
        "cover.jpg",
        "COVER.JPEG",
        "cover.png",
        "cover.webp",
        "01. chapter.cover.jpg",
        "01. chapter.COVER.JPEG",
        "nested.cover.PNG",
        "track.opf",
        "METADATA.OPF",
    ],
)
def test_builtin_sidecars_are_ignored_case_insensitively(name: str) -> None:
    assert is_builtin_ignored_file(name) is True


@pytest.mark.parametrize(
    "name",
    ["chapter.jpg", "cover-art.jpg", "mycover.webp", "book.epub", "chapter.mp3"],
)
def test_builtin_ignore_does_not_hide_readable_or_ordinary_image_files(
    name: str,
) -> None:
    assert is_builtin_ignored_file(name) is False


def test_configured_globs_match_basename_and_posix_relative_path() -> None:
    patterns = "*.tmp\n**/temp/**\n缓存"

    assert matches_configured_ignore_patterns("book/draft.tmp", patterns) is True
    assert matches_configured_ignore_patterns("book/temp/01.mp3", patterns) is True
    assert matches_configured_ignore_patterns("book/缓存文件.mp3", patterns) is True
    assert matches_configured_ignore_patterns("book/01.mp3", patterns) is False


def test_source_entry_combines_builtin_library_and_global_rules() -> None:
    assert should_ignore_source_entry(
        relative_path="book/01.cover.webp",
        name="01.cover.webp",
        is_regular_file=True,
        ignore_hidden=False,
        library_patterns=None,
        global_patterns="",
    )
    assert should_ignore_source_entry(
        relative_path="book/cache/01.mp3",
        name="01.mp3",
        is_regular_file=True,
        ignore_hidden=False,
        library_patterns="**/cache/**",
        global_patterns="",
    )
    assert should_ignore_source_entry(
        relative_path="book/01.part",
        name="01.part",
        is_regular_file=True,
        ignore_hidden=False,
        library_patterns=None,
        global_patterns="*.part",
    )
