from __future__ import annotations

from pathlib import Path

import pytest

from app.services import default_cover


@pytest.mark.parametrize(
    "value",
    [
        "covers/default-book-cover-v1.png",
        "covers/default-book-cover-v2.webp",
        "/abs/storage/covers/default-book-cover-v1.png",
        Path("covers/default-book-cover-v2.webp"),
    ],
)
def test_recognizes_bundled_default_cover(value: object) -> None:
    assert default_cover.is_default_cover_path(value) is True


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "covers/own.png",
        "covers/default-book-cover-v9.webp",
        "../outside.png",
        "default-book-cover-v2.webp.bak",
    ],
)
def test_rejects_real_and_unrelated_paths(value: object) -> None:
    assert default_cover.is_default_cover_path(value) is False


def test_bundled_asset_stays_a_compressed_webp() -> None:
    asset = default_cover.DEFAULT_COVER_ASSET_PATH
    assert asset.is_file()
    assert asset.suffix == ".webp"
    assert asset.stat().st_size <= 64 * 1024
