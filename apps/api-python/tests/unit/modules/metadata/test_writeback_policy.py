from app.contracts.publication_titles import (
    finalize_volume_title,
    publication_title_for_volume,
    split_publication_volume_title,
    titles_from_local_source,
)


def test_publication_title_appends_explicit_integer_volume_number() -> None:
    assert publication_title_for_volume("鬼灭之刃", 2) == "鬼灭之刃 Vol.2"


def test_publication_title_preserves_fractional_volume_number() -> None:
    assert publication_title_for_volume("短篇集", 2.5) == "短篇集 Vol.2.5"


def test_publication_title_does_not_invent_or_duplicate_volume_number() -> None:
    assert publication_title_for_volume("单行本", None) == "单行本"
    assert publication_title_for_volume("鬼灭之刃 Vol.2", 2) == "鬼灭之刃 Vol.2"


def test_publication_title_replaces_a_conflicting_existing_volume_suffix() -> None:
    assert publication_title_for_volume("鬼灭之刃 Vol.1", 2) == "鬼灭之刃 Vol.2"


def test_split_volume_suffix_removes_path_separator() -> None:
    assert split_publication_volume_title("路径优先作品-Vol.09") == (
        "路径优先作品",
        9,
    )


def test_chinese_volume_title_is_not_duplicated() -> None:
    assert split_publication_volume_title("第二卷") == ("第二卷", 2)
    assert publication_title_for_volume("第二卷", 2) == "第二卷"


def test_numbered_title_is_split_into_work_and_volume_titles() -> None:
    titles = titles_from_local_source(
        "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 Vol.1"
    )

    assert (
        titles.work_title
        == "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了"
    )
    assert titles.volume_title == (
        "辣妹因为惩罚游戏才向我这个边缘人告白，但显然是真心爱上我了 Vol.1"
    )
    assert titles.volume_index == 1


def test_structured_series_keeps_an_independent_subtitle() -> None:
    titles = titles_from_local_source("魔法石", series_name="哈利波特", volume_index=1)

    assert titles.work_title == "哈利波特"
    assert titles.volume_title == "魔法石"
    assert (
        finalize_volume_title(
            titles.work_title, titles.volume_title, titles.volume_index
        )
        == "魔法石"
    )


def test_missing_volume_title_is_generated_only_after_resolution() -> None:
    assert finalize_volume_title("鬼灭之刃", None, 1) == "鬼灭之刃 Vol.1"
    assert finalize_volume_title("独立作品", None, None) == "独立作品"
