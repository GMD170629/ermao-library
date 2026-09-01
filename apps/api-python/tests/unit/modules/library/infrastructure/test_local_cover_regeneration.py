from __future__ import annotations

from pathlib import Path

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.library.application.local_cover_regeneration import (
    ResourceLocalMetadataSource,
)
from app.modules.library.infrastructure.local_cover_regeneration import (
    FilesystemLocalMetadataCoverParser,
)
from app.modules.metadata.public import (
    FilesystemLocalMetadataInspector,
    LocalAudioMetadata,
    LocalCoverPayload,
    LocalMetadataCandidate,
)


def test_audiobook_directory_uses_shared_priority_and_first_ordered_asset(
    tmp_path: Path,
) -> None:
    resource_directory = tmp_path / "有声书"
    resource_directory.mkdir()
    first = resource_directory / "01.m4a"
    second = resource_directory / "02.m4a"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    inspected: list[str] = []

    def read_audio(path: Path) -> LocalAudioMetadata:
        inspected.append(path.name)
        return LocalAudioMetadata(cover_data=f"embedded-{path.stem}".encode())

    def read_sidecar(
        path: Path,
        *,
        directory: bool,
    ) -> LocalMetadataCandidate:
        assert (path, directory) == (resource_directory, True)
        return LocalMetadataCandidate(
            source="SIDECAR_OPF",
            metadata=PublicationMetadata(title="旁车标题"),
            cover=LocalCoverPayload(b"sidecar-cover"),
        )

    parser = FilesystemLocalMetadataCoverParser(
        FilesystemLocalMetadataInspector(
            audio_reader=read_audio,
            sidecar_reader=read_sidecar,
        )
    )

    result = parser.extract_cover(
        ResourceLocalMetadataSource(
            resource_id="resource",
            book_id="book",
            source_node_id="node",
            adapter_id="audiobook-directory",
            source_format="AUDIOBOOK",
            root_path=tmp_path,
            resource_relative_path="有声书",
            asset_relative_paths=("有声书/01.m4a", "有声书/02.m4a"),
            local_metadata_priority=("SIDECAR_OPF", "EMBEDDED", "PATH"),
        )
    )

    assert result.content == b"sidecar-cover"
    assert inspected == [first.name]


def test_missing_resource_root_returns_stable_failure(tmp_path: Path) -> None:
    parser = FilesystemLocalMetadataCoverParser(FilesystemLocalMetadataInspector())

    result = parser.extract_cover(
        ResourceLocalMetadataSource(
            resource_id="resource",
            book_id="book",
            source_node_id="node",
            adapter_id="epub",
            source_format="EPUB",
            root_path=tmp_path / "missing",
            resource_relative_path="book.epub",
            asset_relative_paths=("book.epub",),
            local_metadata_priority=("SIDECAR_OPF", "EMBEDDED", "PATH"),
        )
    )

    assert result.content is None
    assert result.failure_code == "LOCAL_METADATA_SOURCE_UNAVAILABLE"
