from app.modules.library.domain.asset_titles import (
    AssetTitleCandidate,
    resolve_asset_display_titles,
)


def test_unique_meaningful_metadata_title_wins() -> None:
    titles = resolve_asset_display_titles(
        (AssetTitleCandidate("a1", "精绝古城 第一集", "01.mp3"),)
    )

    assert titles == {"a1": "精绝古城 第一集"}


def test_missing_generic_and_duplicate_titles_fall_back_to_source_filename() -> None:
    titles = resolve_asset_display_titles(
        (
            AssetTitleCandidate("a1", None, "01.mp3"),
            AssetTitleCandidate("a2", "正文", "02.mp3"),
            AssetTitleCandidate("a3", "重复标题", "03.mp3"),
            AssetTitleCandidate("a4", "  重复标题  ", "04.mp3"),
        )
    )

    assert titles == {
        "a1": "01.mp3",
        "a2": "02.mp3",
        "a3": "03.mp3",
        "a4": "04.mp3",
    }
