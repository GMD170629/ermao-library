from __future__ import annotations

import pytest

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.imports.application.dto import BookIdentityDTO
from app.modules.imports.application.identity_resolution import (
    apply_requested_identity,
    resolve_import_metadata,
)


def _path_identity(
    *,
    title: str,
    author: str = "未知作者",
    confidence: float = 0.62,
    volume_index: float | None = None,
    source: str = "regex",
) -> BookIdentityDTO:
    return BookIdentityDTO(
        title=title,
        author=author,
        volume_index=volume_index,
        source=source,
        confidence=confidence,
        logical_path=f"我的书库/{title}.epub",
    )


def test_explicit_fields_are_the_only_pre_format_identity_override() -> None:
    resolved = apply_requested_identity(
        _path_identity(title="路径标题", author="路径作者", volume_index=3),
        requested_title="用户标题",
    )

    assert (resolved.title, resolved.author, resolved.volume_index) == (
        "用户标题",
        "路径作者",
        3,
    )
    assert resolved.source == "requested"
    assert resolved.selection_reason == "explicit_user_fields"
    assert [evidence.source for evidence in resolved.evidence] == [
        "regex",
        "requested",
    ]


def test_no_explicit_fields_preserve_unmodified_path_identity() -> None:
    path_identity = _path_identity(title="路径标题", author="路径作者", volume_index=3)

    resolved = apply_requested_identity(path_identity)

    assert (resolved.title, resolved.author, resolved.volume_index) == (
        "路径标题",
        "路径作者",
        3,
    )
    assert resolved.source == "regex"
    assert resolved.selection_reason is None


def test_path_priority_uses_path_title_and_volume_then_fills_missing_author() -> None:
    identity, resolved = resolve_import_metadata(
        _path_identity(title="路径作品", volume_index=9),
        embedded=PublicationMetadata(
            title="内嵌作品 Vol.8",
            authors=("内嵌作者",),
            description="内嵌简介",
            volume_index=8,
        ),
        sidecar=PublicationMetadata(
            title="OPF作品 Vol.2",
            authors=("OPF作者",),
            publisher="OPF出版社",
            volume_index=2,
        ),
        source_order=("PATH", "EMBEDDED", "SIDECAR_OPF"),
        path_publication_title="路径作品 Vol.9",
    )

    assert (identity.title, identity.author, identity.volume_index) == (
        "路径作品",
        "内嵌作者",
        9,
    )
    assert resolved.metadata.description == "内嵌简介"
    assert resolved.metadata.publisher == "OPF出版社"
    assert dict(resolved.field_sources) == {
        "title": "PATH",
        "author": "EMBEDDED",
        "description": "EMBEDDED",
        "volumeIndex": "PATH",
        "publisher": "SIDECAR_OPF",
        "volumeTitle": "PATH",
    }


def test_lower_priority_series_does_not_replace_higher_priority_title() -> None:
    identity, resolved = resolve_import_metadata(
        _path_identity(title="路径作品", author="路径作者", volume_index=4),
        embedded=None,
        sidecar=PublicationMetadata(
            title="OPF作品 Vol.2",
            authors=("OPF作者",),
            series_name="OPF系列",
            volume_index=2,
        ),
        source_order=("PATH", "EMBEDDED", "SIDECAR_OPF"),
        path_publication_title="路径作品 Vol.4",
    )

    assert (identity.title, identity.author, identity.volume_index) == (
        "路径作品",
        "路径作者",
        4,
    )
    assert resolved.metadata.series_name == "OPF系列"
    assert resolved.source_for("title") == "PATH"
    assert resolved.source_for("seriesName") == "SIDECAR_OPF"


def test_default_priority_still_uses_sidecar_for_every_populated_field() -> None:
    identity, resolved = resolve_import_metadata(
        _path_identity(title="路径作品", author="路径作者", volume_index=9),
        embedded=PublicationMetadata(
            title="内嵌作品 Vol.8", authors=("内嵌作者",), volume_index=8
        ),
        sidecar=PublicationMetadata(
            title="OPF作品 Vol.2", authors=("OPF作者",), volume_index=2
        ),
        source_order=("SIDECAR_OPF", "EMBEDDED", "PATH"),
        path_publication_title="路径作品 Vol.9",
    )

    assert (identity.title, identity.author, identity.volume_index) == (
        "OPF作品",
        "OPF作者",
        2,
    )
    assert resolved.metadata.volume_title == "OPF作品 Vol.2"
    assert resolved.source_for("title") == "SIDECAR_OPF"
    assert resolved.source_for("author") == "SIDECAR_OPF"
    assert resolved.source_for("volumeIndex") == "SIDECAR_OPF"


@pytest.mark.parametrize(
    ("volume_title", "volume_index"),
    [
        ("作品 (3)", 3.0),
        ("Vol.4 作品", 4.0),
        ("作品_005", 5.0),
        ("作品 6", 6.0),
    ],
)
def test_complete_path_snapshot_is_not_split_or_rewritten_again(
    volume_title: str,
    volume_index: float,
) -> None:
    identity, resolved = resolve_import_metadata(
        _path_identity(title="作品", author="路径作者", volume_index=volume_index),
        embedded=None,
        sidecar=None,
        source_order=("PATH", "EMBEDDED", "SIDECAR_OPF"),
        path_metadata=PublicationMetadata(
            title="作品",
            volume_title=volume_title,
            authors=("路径作者",),
            volume_index=volume_index,
        ),
    )

    assert identity.title == "作品"
    assert resolved.metadata.volume_title == volume_title
    assert resolved.metadata.volume_index == volume_index
