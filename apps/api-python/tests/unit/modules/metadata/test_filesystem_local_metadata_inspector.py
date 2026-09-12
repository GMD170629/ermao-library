from __future__ import annotations

from pathlib import Path

import pytest

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


@pytest.mark.parametrize(
    ("source_format", "filename"),
    (("AUDIOBOOK_DIR", "01.m4b"), ("IMAGE_DIR", "第 02 页 & image.png")),
)
def test_directory_inspector_passes_resource_directory_to_sidecar_reader(
    tmp_path: Path,
    source_format: str,
    filename: str,
) -> None:
    resource = tmp_path / "图片目录 Images [01]"
    resource.mkdir()
    source = resource / filename
    source.write_bytes(b"asset")
    path_only = FilesystemLocalMetadataInspector().inspect(
        source,
        resource_path=resource,
        source_format=source_format,
    )
    assert path_only.metadata.title == "图片目录 Images"
    assert path_only.metadata.volume_title == resource.name
    assert path_only.metadata.author is None
    assert dict(path_only.field_sources)["title"] == "PATH"
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
        source_format=source_format,
        audio=LocalAudioMetadata(author="作者")
        if source_format == "AUDIOBOOK_DIR"
        else None,
    )

    assert seen == [(resource, True)]
    assert resolved.metadata.title == "旁车标题"
    assert dict(resolved.field_sources)["title"] == "SIDECAR_OPF"
    assert resolved.metadata.authors == (
        ("作者",) if source_format == "AUDIOBOOK_DIR" else ()
    )


@pytest.mark.parametrize(
    "source_format", ["AUDIOBOOK_DIR", "IMAGE_DIR", "EPUB", "PDF", "CBZ", "AUDIO"]
)
def test_resource_title_preserves_path_for_every_format(tmp_path, source_format):
    name = "鬼吹灯I-1-精绝古城 (全50集)"
    directory = source_format in {"AUDIOBOOK_DIR", "IMAGE_DIR"}
    resource = tmp_path / name
    source = resource / "01.mp3" if directory else tmp_path / f"{name}.epub"
    resolved = FilesystemLocalMetadataInspector().inspect(
        source,
        resource_path=resource,
        source_format=source_format,
    )
    assert resolved.metadata.volume_title == name
    assert resolved.metadata.title == "鬼吹灯I"
    assert resolved.metadata.authors == ()


@pytest.mark.parametrize("kind", ["SIDECAR_OPF", "EMBEDDED"])
@pytest.mark.parametrize("volume_title", [None, "明确卷标题"])
def test_higher_priority_title_beats_path_volume(tmp_path, kind, volume_title):
    candidate = LocalMetadataCandidate(
        source=kind,
        metadata=PublicationMetadata(title="元数据标题", volume_title=volume_title),
    )
    resolved = FilesystemLocalMetadataInspector().inspect(
        tmp_path / "路径-副标题.epub",
        source_format="EPUB",
        sidecar=candidate if kind == "SIDECAR_OPF" else None,
        embedded=candidate if kind == "EMBEDDED" else None,
    )
    assert resolved.metadata.volume_title == (volume_title or "元数据标题")
    assert dict(resolved.field_sources)["volumeTitle"] == kind


def test_path_first_preserves_volume_even_with_embedded_index(tmp_path):
    resolved = FilesystemLocalMetadataInspector().inspect(
        tmp_path / "完整标题.epub",
        source_format="EPUB",
        embedded=LocalMetadataCandidate(
            source="EMBEDDED",
            metadata=PublicationMetadata(title="内嵌标题", volume_index=2),
        ),
        source_order=("PATH", "EMBEDDED", "SIDECAR_OPF"),
    )
    assert resolved.metadata.volume_title == "完整标题"
    assert resolved.metadata.volume_index == 2
