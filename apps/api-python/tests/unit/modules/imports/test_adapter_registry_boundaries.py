"""Adapter registry boundary checks with real tiny fixtures / temp files."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from app.modules.imports.application.local_metadata import LocalCoverPayload
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    ResourceAdapterId,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
)
from app.modules.library.domain.readable_resource_states import AssetRole


def test_suffix_matching_boundaries() -> None:
    assert unique_adapter_or_none(match_file_adapters("a.txt")) is not None
    assert unique_adapter_or_none(match_file_adapters("a.TXT")) is not None
    assert unique_adapter_or_none(match_file_adapters("readme.md")) is None
    assert unique_adapter_or_none(match_file_adapters("track.mp3")) is not None
    directory = next(
        s
        for s in ADAPTER_SPECS
        if s.adapter_id is ResourceAdapterId.AUDIOBOOK_DIRECTORY
    )
    assert directory.is_directory_adapter is True


def test_registry_parses_real_txt(tmp_path: Path) -> None:
    path = tmp_path / "chapter.txt"
    path.write_text("hello world\n", encoding="utf-8")
    adapter = unique_adapter_or_none(match_file_adapters(path.name))
    assert adapter is not None
    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        adapter=adapter,
        role=AssetRole.PRIMARY,
    )
    assert result.ok is True
    assert result.asset is not None
    assert result.resource_title == "chapter"


def test_registry_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "gone.txt"
    adapter = unique_adapter_or_none(match_file_adapters("gone.txt"))
    assert adapter is not None
    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        adapter=adapter,
        role=AssetRole.PRIMARY,
    )
    assert result.ok is False
    assert result.error_code == "FILE_MISSING"


def test_registry_image_page_uses_stem(tmp_path: Path) -> None:
    path = tmp_path / "001.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    adapter = next(
        s for s in ADAPTER_SPECS if s.adapter_id is ResourceAdapterId.IMAGE_DIRECTORY
    )
    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        adapter=adapter,
        role=AssetRole.PAGE,
    )
    assert result.ok is True
    assert result.asset is not None
    assert result.asset.role is AssetRole.PAGE
    assert result.asset.sort_key == "001.png"


def test_registry_epub_merges_sidecar_embedded_path_and_cover(tmp_path: Path) -> None:
    path = tmp_path / "路径书名.epub"
    cover = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "META-INF/container.xml",
            '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        )
        archive.writestr(
            "OPS/book.opf",
            """<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata>
            <dc:title>内嵌标题</dc:title><dc:creator>内嵌作者</dc:creator>
            <meta name="cover" content="cover-image"/></metadata>
            <manifest><item id="cover-image" href="cover.png" media-type="image/png"/></manifest></package>""",
        )
        archive.writestr("OPS/cover.png", cover)
    path.with_suffix(".opf").write_text(
        '<package xmlns:dc="http://purl.org/dc/elements/1.1/"><metadata><dc:title>旁车标题</dc:title></metadata></package>',
        encoding="utf-8",
    )
    adapter = unique_adapter_or_none(match_file_adapters(path.name))
    assert adapter is not None

    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        adapter=adapter,
        role=AssetRole.PRIMARY,
    )

    assert result.local_metadata is not None
    assert result.local_metadata.metadata.title == "旁车标题"
    assert result.local_metadata.metadata.author == "内嵌作者"
    assert result.local_metadata.cover == LocalCoverPayload(cover)
