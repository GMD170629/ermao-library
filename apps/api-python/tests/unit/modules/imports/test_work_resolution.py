from __future__ import annotations

import pytest

from app.modules.imports.application.work_resolution import resolve_work_identity


@pytest.mark.parametrize(
    ("values", "expected_key", "expected_kind"),
    (
        (
            {
                "title": "路径标题",
                "author": "路径作者",
                "isbn": "978-7-111-11111-5",
                "identifier": "provider:book-1",
                "series_name": "系列名",
            },
            "isbn:9787111111115",
            "ISBN",
        ),
        (
            {
                "title": "路径标题",
                "author": "路径作者",
                "identifier": "provider:book-1",
                "series_name": "系列名",
            },
            "identifier:providerbook1",
            "IDENTIFIER",
        ),
        (
            {
                "title": "第一卷",
                "author": "系列作者",
                "series_name": "完整系列",
            },
            "series:完整系列:系列作者",
            "SERIES_AUTHOR",
        ),
        (
            {"title": "最终标题", "author": "最终作者"},
            "最终标题:最终作者",
            "TITLE_AUTHOR",
        ),
    ),
)
def test_work_identity_uses_only_final_metadata_in_priority_order(
    values: dict[str, str], expected_key: str, expected_kind: str
) -> None:
    decision = resolve_work_identity(**values)

    assert decision.merge_key == expected_key
    assert decision.kind == expected_kind


def test_series_identity_does_not_depend_on_volume_index() -> None:
    decision = resolve_work_identity(
        title="没有卷号的卷册标题",
        author="系列作者",
        series_name="作品系列",
    )

    assert decision.merge_key == "series:作品系列:系列作者"
    assert decision.kind == "SERIES_AUTHOR"


@pytest.mark.parametrize("identifier", (None, "urn:uuid:book-id", "550e8400-e29b-41d4-a716-446655440000"))
def test_missing_or_uuid_identifier_falls_through_to_series(
    identifier: str | None,
) -> None:
    decision = resolve_work_identity(
        title="卷册标题",
        author="作者",
        identifier=identifier,
        series_name="系列",
    )

    assert decision.merge_key == "series:系列:作者"
