from __future__ import annotations

import pytest

from app.modules.imports.application.identity_policy import (
    explicit_volume_range_start,
    normalize_identity_part,
    parse_bracketed_series_identity,
    split_numeric_volume_fallback,
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
    ("folder_name", "filename", "expected"),
    [
        ("[活着][余华]", "活着.epub", ("活着", "余华")),
        (
            "[辣妹因为惩罚游戏才向我这个边缘人告白][結石][Vol.01-Vol.10]",
            "辣妹因为惩罚游戏才向我这个边缘人告白 09.epub",
            ("辣妹因为惩罚游戏才向我这个边缘人告白", "結石"),
        ),
        (
            "[Chainsaw Man][电锯人][藤本タツキ][Vol.01-Vol.11]",
            "VOL11.zip",
            ("电锯人", "藤本タツキ"),
        ),
    ],
)
def test_bracketed_series_identity_selects_title_and_author(
    folder_name: str,
    filename: str,
    expected: tuple[str, str],
) -> None:
    assert parse_bracketed_series_identity(folder_name, filename) == expected


def test_bracketed_series_identity_rejects_non_series_folder_names() -> None:
    assert parse_bracketed_series_identity("[Title] extra [Author]") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("FX戦士久留美 (1)", ("FX戦士久留美", 1)),
        ("FX戦士久留美 [02]", ("FX戦士久留美", 2)),
        ("FX戦士久留美_003", ("FX戦士久留美", 3)),
        ("004 FX戦士久留美", ("FX戦士久留美", 4)),
    ],
)
def test_numeric_volume_fallback_accepts_short_standalone_numbers(
    value: str,
    expected: tuple[str, float],
) -> None:
    assert split_numeric_volume_fallback(value) == expected


@pytest.mark.parametrize("value", ["作品2024版", "作品123456特别篇"])
def test_numeric_volume_fallback_ignores_long_attached_numbers(value: str) -> None:
    assert split_numeric_volume_fallback(value) is None


def test_identity_normalization_is_unicode_and_separator_insensitive() -> None:
    assert normalize_identity_part("  Ａuthor - Name（特别） ") == "authorname特别"
