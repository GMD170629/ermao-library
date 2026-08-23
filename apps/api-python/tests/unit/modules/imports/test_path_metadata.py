import pytest

from app.modules.imports.application.identity_policy import (
    explicit_volume_range_start,
    split_explicit_volume,
    split_numeric_volume_fallback,
)


@pytest.mark.parametrize(
    ("filename", "title", "volume_index"),
    [
        ("作品 (3)", "作品", 3.0),
        ("Vol.4 作品", "作品", 4.0),
        ("作品_005", "作品", 5.0),
        ("作品 6", "作品", 6.0),
    ],
)
def test_filename_identity_preserves_release_title_and_parsed_index(
    filename: str,
    title: str,
    volume_index: float,
) -> None:
    parsed = split_explicit_volume(filename) or split_numeric_volume_fallback(filename)

    assert parsed == (title, volume_index)


def test_filename_range_uses_start_without_reading_directory_neighbors() -> None:
    assert explicit_volume_range_start("作品 第7-9卷") == 7.0


def test_unmarked_year_range_is_not_a_publication_volume() -> None:
    assert explicit_volume_range_start("作品 2020-2024") is None


def test_filename_identity_does_not_create_grouping_contract() -> None:
    parsed = split_explicit_volume("作品") or split_numeric_volume_fallback("作品")

    assert parsed is None
