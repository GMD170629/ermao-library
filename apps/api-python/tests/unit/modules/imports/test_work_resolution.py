from __future__ import annotations

import pytest

from app.modules.imports.application.work_resolution import resolve_work_identity


@pytest.mark.parametrize(
    "title",
    (
        "作品标题",
        "  作品标题  ",
        "作品·标题",
        "作品-标题",
    ),
)
def test_work_identity_uses_only_normalized_work_title(title: str) -> None:
    decision = resolve_work_identity(title=title)

    assert decision.merge_key == "作品标题"
    assert decision.kind == "TITLE"


def test_same_title_always_has_the_same_work_identity() -> None:
    first = resolve_work_identity(title="同一作品")
    second = resolve_work_identity(title="同一作品")

    assert first.merge_key == second.merge_key == "同一作品"


def test_different_titles_never_share_a_work_identity() -> None:
    first = resolve_work_identity(title="作品甲")
    second = resolve_work_identity(title="作品乙")

    assert first.merge_key == "作品甲"
    assert second.merge_key == "作品乙"
    assert first.merge_key != second.merge_key
