from __future__ import annotations

from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationLink,
    PublicationRevision,
    PublicationTocEntry,
)
from app.modules.publications.domain.navigation import flatten_publication_navigation


def _publication() -> NormalizedPublication:
    return NormalizedPublication(
        identifier="urn:test:navigation",
        title="目录测试",
        author=None,
        language="zh-CN",
        reading_progression="ltr",
        revision=PublicationRevision(
            source_size_bytes=1024,
            source_mtime_ms=1234,
            parser="test-parser:1",
            normalization="test-normalization:1",
        ),
        reading_order=(
            PublicationLink("Text/part.xhtml", "application/xhtml+xml"),
            PublicationLink("Text/end.xhtml", "application/xhtml+xml"),
        ),
        resources=(),
        toc=(
            PublicationTocEntry(
                href="Text/part.xhtml#part",
                title="第一部",
                children=(
                    PublicationTocEntry(
                        href="Text/part.xhtml#chapter-1",
                        title="第一章",
                    ),
                ),
            ),
            PublicationTocEntry(href="Text/end.xhtml", title="尾声"),
        ),
    )


def test_flatten_navigation_is_zero_based_preorder_with_stable_metadata() -> None:
    first = flatten_publication_navigation(
        resource_id="resource-navigation",
        publication=_publication(),
    )
    second = flatten_publication_navigation(
        resource_id="resource-navigation",
        publication=_publication(),
    )

    assert first == second
    assert [entry.title for entry in first] == ["第一部", "第一章", "尾声"]
    assert [entry.sort_order for entry in first] == [0, 1, 2]
    assert [entry.path for entry in first] == [(0,), (0, 0), (1,)]
    assert [entry.level for entry in first] == [0, 1, 0]
    assert [entry.reading_order_position for entry in first] == [1, 1, 2]
    assert all(entry.id == entry.navigation_key for entry in first)
    assert all(entry.id.startswith("pubnav_") for entry in first)
    assert [entry.media_type for entry in first] == [
        "application/xhtml+xml",
        "application/xhtml+xml",
        "application/xhtml+xml",
    ]
