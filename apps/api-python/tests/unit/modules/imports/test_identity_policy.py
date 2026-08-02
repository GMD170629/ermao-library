from __future__ import annotations

import pytest

from app.modules.imports.application.identity_policy import (
    directory_merge_title_similarity,
    directory_merge_titles_match,
    explicit_volume_range_start,
    normalize_directory_merge_title,
    split_explicit_volume,
)


@pytest.mark.parametrize(
    ("publication_title", "expected_title", "expected_volume"),
    [
        ("第01卷大雄的恐龙", "大雄的恐龙", 1),
        ("哆啦A梦第02卷大雄的宇宙开拓史", "哆啦A梦大雄的宇宙开拓史", 2),
        ("大雄的魔界大冒险 第05卷", "大雄的魔界大冒险", 5),
        ("Vol.03 大雄与铁人兵团", "大雄与铁人兵团", 3),
        ("Doraemon Volume 04 Adventure", "Doraemon Adventure", 4),
        ("Doraemon Adventure v05", "Doraemon Adventure", 5),
        ("前传01册特别篇", "前传特别篇", 1),
        ("特别篇 02集 后日谈", "特别篇 后日谈", 2),
    ],
)
def test_explicit_volume_marker_is_recognized_at_any_title_position(
    publication_title: str,
    expected_title: str,
    expected_volume: float,
) -> None:
    assert split_explicit_volume(publication_title) == (
        expected_title,
        expected_volume,
    )


@pytest.mark.parametrize(
    "publication_title",
    [
        "作品2024版",
        "V字仇杀队",
        "合集 Vol.01-Vol.24",
        "合集 第01卷-第24卷",
    ],
)
def test_explicit_volume_marker_ignores_plain_numbers_and_volume_ranges(
    publication_title: str,
) -> None:
    assert split_explicit_volume(publication_title) is None


@pytest.mark.parametrize(
    ("publication_title", "expected_start"),
    [
        ("瑞克与莫蒂 - 第001-005话", 1),
        ("作品 Vol.06-Vol.10", 6),
        ("作品 卷11~15", 11),
        ("作品 16至20集", 16),
        ("作品 第21到25章", 21),
    ],
)
def test_explicit_volume_range_returns_first_publication_number(
    publication_title: str,
    expected_start: float,
) -> None:
    assert explicit_volume_range_start(publication_title) == expected_start


@pytest.mark.parametrize("publication_title", ["2020-2024年", "版本 1-2", "作品名"])
def test_volume_range_requires_a_publication_marker(publication_title: str) -> None:
    assert explicit_volume_range_start(publication_title) is None


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("東京卍復仇者 卷01", "東京卍復仇者 卷31"),
        ("作品2023 全彩版", "作品2026 全彩版"),
        ("第01部 第002册", "第99部 第120册"),
        ("作品１２．５", "作品3.0"),
    ],
)
def test_directory_merge_title_treats_numeric_values_as_equivalent(
    left: str,
    right: str,
) -> None:
    assert normalize_directory_merge_title(left) == normalize_directory_merge_title(
        right
    )


def test_directory_merge_title_preserves_number_position_and_surrounding_text() -> None:
    assert normalize_directory_merge_title(
        "作品01前传"
    ) != normalize_directory_merge_title("作品前传01")
    assert normalize_directory_merge_title(
        "作品01全彩"
    ) != normalize_directory_merge_title("作品01黑白")


def test_directory_merge_title_similarity_unifies_numbers_before_comparison() -> None:
    assert directory_merge_title_similarity("作品2023全彩版", "作品2026全彩版") == 1.0


def test_directory_merge_title_similarity_accepts_exactly_seventy_percent() -> None:
    assert directory_merge_title_similarity(
        "abcdefghij", "abcdefgxyz"
    ) == pytest.approx(0.7)
    assert directory_merge_titles_match("abcdefghij", "abcdefgxyz") is True


def test_directory_merge_title_similarity_rejects_below_seventy_percent() -> None:
    assert directory_merge_titles_match("abcdefghij", "abcdefwxyz") is False
    assert directory_merge_titles_match("", "") is False
