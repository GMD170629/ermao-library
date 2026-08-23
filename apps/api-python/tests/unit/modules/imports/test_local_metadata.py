import pytest

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    validate_local_metadata_priority,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.modules.imports.application.local_metadata import (
    LocalCoverPayload,
    LocalMetadataCandidate,
    resolve_local_metadata,
)


def test_default_priority_is_opf_then_embedded_then_path() -> None:
    assert DEFAULT_LOCAL_METADATA_PRIORITY == (
        "SIDECAR_OPF",
        "EMBEDDED",
        "PATH",
    )


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


def test_priority_validation_normalizes_source_names() -> None:
    assert (
        validate_local_metadata_priority(["sidecar_opf", "embedded", "path"])
        == DEFAULT_LOCAL_METADATA_PRIORITY
    )


def test_local_metadata_resolves_every_field_and_cover_by_configured_order() -> None:
    embedded_cover = LocalCoverPayload(b"embedded")
    resolved = resolve_local_metadata(
        (
            LocalMetadataCandidate(
                source="SIDECAR_OPF",
                metadata=PublicationMetadata(title="旁车标题"),
            ),
            LocalMetadataCandidate(
                source="EMBEDDED",
                metadata=PublicationMetadata(title="内嵌标题", authors=("内嵌作者",)),
                cover=embedded_cover,
            ),
            LocalMetadataCandidate(
                source="PATH",
                metadata=PublicationMetadata(title="路径标题", language="zh-CN"),
            ),
        )
    )

    assert resolved.metadata.title == "旁车标题"
    assert resolved.metadata.author == "内嵌作者"
    assert resolved.metadata.language == "zh-CN"
    assert resolved.cover is embedded_cover
    assert dict(resolved.field_sources) == {
        "title": "SIDECAR_OPF",
        "author": "EMBEDDED",
        "language": "PATH",
        "cover": "EMBEDDED",
    }


def test_local_metadata_honors_non_default_cover_priority() -> None:
    resolved = resolve_local_metadata(
        (
            LocalMetadataCandidate(
                source="SIDECAR_OPF",
                metadata=PublicationMetadata(title="旁车"),
                cover=LocalCoverPayload(b"sidecar"),
            ),
            LocalMetadataCandidate(
                source="EMBEDDED",
                metadata=PublicationMetadata(title="内嵌"),
                cover=LocalCoverPayload(b"embedded"),
            ),
        ),
        ("EMBEDDED", "PATH", "SIDECAR_OPF"),
    )

    assert resolved.metadata.title == "内嵌"
    assert resolved.cover == LocalCoverPayload(b"embedded")
