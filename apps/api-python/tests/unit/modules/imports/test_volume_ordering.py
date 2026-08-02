from __future__ import annotations

from app.modules.imports.application.volume_ordering import (
    VolumeOrderingEntry,
    desired_volume_sort_orders,
    natural_title_key,
)


def _entry(
    volume_id: str,
    title: str,
    volume_index: float | None,
) -> VolumeOrderingEntry:
    return VolumeOrderingEntry(
        volume_id=volume_id,
        title=title,
        volume_index=volume_index,
        sort_order=999,
    )


def test_numbered_volumes_use_numeric_volume_order() -> None:
    entries = [
        _entry("sixteen", "第016-020话", 16),
        _entry("one", "第001-005话", 1),
        _entry("six", "第006-010话", 6),
    ]

    assert desired_volume_sort_orders(entries) == {
        "one": 1000,
        "six": 6000,
        "sixteen": 16000,
    }


def test_unnumbered_volumes_use_natural_title_order() -> None:
    entries = [
        _entry("ten", "Appendix 10", None),
        _entry("two", "Appendix 2", None),
        _entry("one", "Appendix 1", None),
    ]

    assert desired_volume_sort_orders(entries) == {
        "one": 0,
        "two": 1000,
        "ten": 2000,
    }
    assert natural_title_key("Ａppendix 2") == natural_title_key("appendix 2")


def test_unnumbered_volumes_follow_numbered_volumes_in_natural_order() -> None:
    entries = [
        _entry("appendix-b", "Appendix B", None),
        _entry("numbered", "第2卷", 2),
        _entry("appendix-a", "Appendix A", None),
    ]

    assert desired_volume_sort_orders(entries) == {
        "numbered": 2000,
        "appendix-a": 3000,
        "appendix-b": 4000,
    }
