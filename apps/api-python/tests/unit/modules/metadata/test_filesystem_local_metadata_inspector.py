from __future__ import annotations

from pathlib import Path

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.metadata.public import (
    FilesystemLocalMetadataInspector,
    LocalAudioMetadata,
    LocalMetadataCandidate,
)


def test_inspector_uses_one_priority_for_path_embedded_and_sidecar(
    tmp_path: Path,
) -> None:
    source = tmp_path / "路径标题.epub"
    source.write_bytes(b"epub")
    embedded_cover = b"embedded"
    sidecar_cover = b"sidecar"

    resolved = FilesystemLocalMetadataInspector().inspect(
        source,
        source_format="EPUB",
        embedded=LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(title="内嵌标题", authors=("作者",)),
            cover=embedded_cover,
        ),
        sidecar=LocalMetadataCandidate(
            source="SIDECAR_OPF",
            metadata=PublicationMetadata(title="旁车标题"),
            cover=sidecar_cover,
        ),
    )

    assert resolved.metadata.title == "旁车标题"
    assert resolved.metadata.author == "作者"
    assert resolved.cover is sidecar_cover
    assert dict(resolved.field_sources)["title"] == "SIDECAR_OPF"


def test_inspector_maps_audio_dto_to_embedded_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.m4b"
    source.write_bytes(b"audio")
    resolved = FilesystemLocalMetadataInspector().inspect(
        source,
        source_format="AUDIO",
        audio=LocalAudioMetadata(
            album="专辑标题",
            author="作者",
            narrator="旁白",
            cover_data=b"cover",
        ),
    )

    assert resolved.metadata.title == "专辑标题"
    assert resolved.metadata.authors == ("作者",)
    assert resolved.metadata.narrators == ("旁白",)
    assert resolved.cover == b"cover"


def test_directory_inspector_passes_resource_directory_to_sidecar_reader(
    tmp_path: Path,
) -> None:
    resource = tmp_path / "作品"
    resource.mkdir()
    source = resource / "01.m4b"
    source.write_bytes(b"audio")
    seen: list[tuple[Path, bool]] = []

    def read_sidecar(path: Path, *, directory: bool) -> LocalMetadataCandidate:
        seen.append((path, directory))
        return LocalMetadataCandidate(
            source="SIDECAR_OPF",
            metadata=PublicationMetadata(title="旁车标题"),
        )

    inspector = FilesystemLocalMetadataInspector(sidecar_reader=read_sidecar)
    resolved = inspector.inspect(
        source,
        resource_path=resource,
        source_format="AUDIOBOOK_DIR",
        audio=LocalAudioMetadata(author="作者"),
    )

    assert seen == [(resource, True)]
    assert resolved.metadata.title == "旁车标题"
    assert resolved.metadata.authors == ("作者",)
