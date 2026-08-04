from __future__ import annotations

import itertools

import pytest

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.imports.application.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    LocalMetadataCandidate,
    LocalMetadataSource,
    resolve_local_metadata,
    validate_local_metadata_priority,
)


def _candidate(source: LocalMetadataSource, **values: object) -> LocalMetadataCandidate:
    return LocalMetadataCandidate(source=source, metadata=PublicationMetadata(**values))


def test_default_priority_resolves_every_field_independently() -> None:
    resolved = resolve_local_metadata(
        (
            _candidate("SIDECAR_OPF", title="OPF 标题", description="OPF 简介"),
            _candidate(
                "EMBEDDED",
                title="内嵌标题",
                authors=("内嵌作者",),
                language="zh",
                volume_index=2,
            ),
            _candidate("PATH", title="路径标题", authors=("路径作者",), volume_index=9),
        )
    )

    assert resolved.metadata.title == "OPF 标题"
    assert resolved.metadata.author == "内嵌作者"
    assert resolved.metadata.description == "OPF 简介"
    assert resolved.metadata.language == "zh"
    assert resolved.metadata.volume_index == 2
    assert dict(resolved.field_sources) == {
        "title": "SIDECAR_OPF",
        "author": "EMBEDDED",
        "description": "SIDECAR_OPF",
        "volumeIndex": "EMBEDDED",
        "language": "EMBEDDED",
        "volumeTitle": "SIDECAR_OPF",
    }


@pytest.mark.parametrize(
    "order", itertools.permutations(DEFAULT_LOCAL_METADATA_PRIORITY)
)
def test_all_source_orders_use_first_non_empty_value(
    order: tuple[LocalMetadataSource, ...],
) -> None:
    candidates = tuple(
        _candidate(source, title=f"{source} 标题", volume_index=index + 1)
        for index, source in enumerate(DEFAULT_LOCAL_METADATA_PRIORITY)
    )
    resolved = resolve_local_metadata(candidates, order)

    assert resolved.metadata.title == f"{order[0]} 标题"
    assert (
        resolved.metadata.volume_index
        == DEFAULT_LOCAL_METADATA_PRIORITY.index(order[0]) + 1
    )
    assert (
        resolved.metadata.volume_title
        == f"{order[0]} 标题 Vol.{DEFAULT_LOCAL_METADATA_PRIORITY.index(order[0]) + 1:g}"
    )


def test_title_volume_title_and_index_are_resolved_independently() -> None:
    resolved = resolve_local_metadata(
        (
            _candidate("SIDECAR_OPF", title="作品"),
            _candidate("EMBEDDED", volume_title="独立副标题"),
            _candidate("PATH", volume_index=2),
        )
    )

    assert resolved.metadata.title == "作品"
    assert resolved.metadata.volume_title == "独立副标题"
    assert resolved.metadata.volume_index == 2
    assert resolved.source_for("title") == "SIDECAR_OPF"
    assert resolved.source_for("volumeTitle") == "EMBEDDED"
    assert resolved.source_for("volumeIndex") == "PATH"


def test_invalid_high_priority_volume_allows_lower_priority_fallback() -> None:
    resolved = resolve_local_metadata(
        (
            _candidate("SIDECAR_OPF", volume_index=float("nan")),
            _candidate("EMBEDDED", volume_index=3),
            _candidate("PATH", volume_index=7),
        )
    )

    assert resolved.metadata.volume_index == 3
    assert resolved.source_for("volumeIndex") == "EMBEDDED"


def test_requested_identity_is_always_higher_than_configured_sources() -> None:
    resolved = resolve_local_metadata(
        (_candidate("SIDECAR_OPF", title="OPF", authors=("OPF 作者",)),),
        requested_title="用户标题",
        requested_author="用户作者",
    )

    assert (resolved.metadata.title, resolved.metadata.author) == (
        "用户标题",
        "用户作者",
    )
    assert resolved.source_for("title") == "REQUESTED"
    assert resolved.source_for("author") == "REQUESTED"


@pytest.mark.parametrize(
    "value",
    (
        ["SIDECAR_OPF", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "REMOTE"],
    ),
)
def test_priority_validation_requires_each_local_source_once(value: list[str]) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_local_metadata_priority(value)
