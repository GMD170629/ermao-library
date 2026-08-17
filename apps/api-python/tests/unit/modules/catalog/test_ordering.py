from __future__ import annotations

from app.modules.catalog.domain.model import PathComparison
from app.modules.catalog.domain.ordering import sorted_paths


def test_unicode_path_order_is_deterministic_for_equivalent_spellings() -> None:
    decomposed = ("cafe\u0301", "Book", "chapter-01.epub")
    composed = ("caf\u00e9", "Book", "chapter-01.epub")

    ordered = sorted_paths(
        (decomposed, composed),
        PathComparison.SENSITIVE,
    )
    assert ordered == (decomposed, composed)


def test_case_collision_is_reported_only_for_insensitive_path_policy() -> None:
    sensitive = sorted_paths(
        (("Books", "Chapter.epub"), ("books", "chapter.epub")),
        PathComparison.SENSITIVE,
    )
    insensitive = sorted_paths(
        (("Books", "Chapter.epub"), ("books", "chapter.epub")),
        PathComparison.INSENSITIVE,
    )

    assert sensitive == (("Books", "Chapter.epub"), ("books", "chapter.epub"))
    assert insensitive == (("Books", "Chapter.epub"), ("books", "chapter.epub"))


def test_natural_name_key_is_locale_independent_and_uses_ascii_number_runs() -> None:
    values = ["第10卷", "第2卷", "第01卷", "第1卷", "第0002卷"]

    ordered = [
        "/".join(path)
        for path in sorted_paths(
            tuple((value,) for value in values),
            PathComparison.SENSITIVE,
        )
    ]

    # Numeric values are compared as integers.  Preserved spelling is the
    # deterministic final tie-breaker for equal numeric values.
    assert ordered == ["第01卷", "第1卷", "第0002卷", "第2卷", "第10卷"]


def test_natural_name_key_handles_mixed_ascii_text_and_leading_zeroes() -> None:
    values = ["track10.mp3", "track002.mp3", "track2.mp3", "track01.mp3"]

    assert [
        "/".join(path)
        for path in sorted_paths(
            tuple((value,) for value in values),
            PathComparison.SENSITIVE,
        )
    ] == ["track01.mp3", "track002.mp3", "track2.mp3", "track10.mp3"]


def test_natural_name_key_does_not_depend_on_input_order() -> None:
    first = ["part11.epub", "part2.epub", "part1.epub"]
    second = list(reversed(first))

    assert sorted_paths(
        tuple((value,) for value in first),
        PathComparison.SENSITIVE,
    ) == sorted_paths(
        tuple((value,) for value in second),
        PathComparison.SENSITIVE,
    )
