from __future__ import annotations

from app.core.natural_sort import natural_sort_key


def test_natural_sort_normalizes_unicode_case_and_numeric_groups() -> None:
    values = [
        "卷/Épisode 10.jpg",
        "卷/e\u0301PISODE 2.jpg",
        "卷/épisode 1.jpg",
    ]

    assert sorted(values, key=natural_sort_key) == [
        "卷/épisode 1.jpg",
        "卷/e\u0301PISODE 2.jpg",
        "卷/Épisode 10.jpg",
    ]


def test_natural_sort_compares_the_complete_relative_path() -> None:
    values = ["part 10/01.jpg", "part 2/10.jpg", "part 2/2.jpg"]

    assert sorted(values, key=natural_sort_key) == [
        "part 2/2.jpg",
        "part 2/10.jpg",
        "part 10/01.jpg",
    ]
