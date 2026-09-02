import pytest

from app.contracts.local_metadata import (
    DEFAULT_LOCAL_METADATA_PRIORITY,
    validate_local_metadata_priority,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.public import (
    FilesystemLocalMetadataInspector,
    LocalMetadataCandidate,
)


@pytest.mark.parametrize(
    "value",
    (
        ["SIDECAR_OPF", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "EMBEDDED"],
        ["SIDECAR_OPF", "EMBEDDED", "REMOTE"],
    ),
)
def test_priority_requires_each_local_source_once(value: list[str]) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_local_metadata_priority(value)


def test_priority_normalizes_source_names() -> None:
    assert (
        validate_local_metadata_priority(["sidecar_opf", "embedded", "path"])
        == DEFAULT_LOCAL_METADATA_PRIORITY
    )


def test_resolution_honors_non_default_field_and_cover_priority(tmp_path) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"epub")
    resolved = FilesystemLocalMetadataInspector().inspect(
        source,
        source_format="EPUB",
        sidecar=LocalMetadataCandidate(
            source="SIDECAR_OPF",
            metadata=PublicationMetadata(title="旁车"),
            cover=b"sidecar",
        ),
        embedded=LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(title="内嵌"),
            cover=b"embedded",
        ),
        source_order=("EMBEDDED", "PATH", "SIDECAR_OPF"),
    )

    assert resolved.metadata.title == "内嵌"
    assert resolved.cover == b"embedded"
