"""Adapter registry boundary checks with real tiny fixtures / temp files."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from app.modules.imports.application.audio_types import (
    AudioChapterMetadata,
    AudioFileMetadata,
)
from app.modules.imports.application.pdf_types import PdfInspection
from app.modules.imports.domain.pdf_content import PdfContentKind, PdfTextEvidence
from app.modules.imports.domain.resource_adapters import (
    ADAPTER_SPECS,
    ResourceAdapterId,
    match_file_adapters,
    unique_adapter_or_none,
)
from app.modules.imports.infrastructure.readable_resource.adapter_registry import (
    RegistryResourceAdapterExecutor,
    _audio_navigation_units,
)
from app.modules.library.domain.readable_resource_states import AssetRole


def _audio_metadata(
    path: Path,
    *,
    chapters: tuple[AudioChapterMetadata, ...] = (),
) -> AudioFileMetadata:
    return AudioFileMetadata(
        path=path,
        title="Track title",
        album="Album",
        author=None,
        narrator=None,
        duration_ms=10_000,
        codec="aac",
        bitrate=None,
        sample_rate=None,
        channels=None,
        disc_number=None,
        track_number=None,
        chapters=chapters,
    )


def test_audio_without_embedded_chapters_has_no_navigation_units(
    tmp_path: Path,
) -> None:
    metadata = _audio_metadata(tmp_path / "track.m4b")

    assert (
        _audio_navigation_units(
            metadata,
            title="Track title",
            mime_type="audio/mp4",
        )
        == ()
    )


def test_audio_embedded_chapters_remain_navigation_units(tmp_path: Path) -> None:
    metadata = _audio_metadata(
        tmp_path / "track.m4b",
        chapters=(
            AudioChapterMetadata(title="Part one", start_ms=0, end_ms=5_000),
            AudioChapterMetadata(title="Part two", start_ms=5_000, end_ms=10_000),
        ),
    )

    units = _audio_navigation_units(
        metadata,
        title="Track title",
        mime_type="audio/mp4",
    )

    assert [(unit.title, unit.start_ms, unit.end_ms) for unit in units] == [
        ("Part one", 0, 5_000),
        ("Part two", 5_000, 10_000),
    ]


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


def test_registry_preserves_inspected_pdf_page_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-test")
    adapter = unique_adapter_or_none(match_file_adapters(path.name))
    assert adapter is not None
    inspection = PdfInspection(
        title="book",
        author="author",
        embedded_title=None,
        embedded_author=None,
        description=None,
        tags=(),
        page_count=7,
        chapters=(),
        raw_metadata={},
        content_kind=PdfContentKind.TEXTUAL,
        text_evidence=PdfTextEvidence(
            inspected_pages=1,
            total_pages=7,
            maximum_effective_characters=20,
            completed=False,
            reason="TEXT_FOUND",
            elapsed_ms=1,
        ),
    )
    monkeypatch.setattr(
        "app.modules.imports.infrastructure.pdf_inspection.inspect_pdf",
        lambda _path: inspection,
    )

    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        adapter=adapter,
        role=AssetRole.PRIMARY,
    )

    assert result.ok is True
    assert result.asset is not None
    assert result.asset.technical.page_count == 7


def test_registry_image_page_uses_stem(tmp_path: Path) -> None:
    resource_path = tmp_path / "图片目录 Images [01]"
    resource_path.mkdir()
    path = resource_path / "第 02 页 & image.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    adapter = next(
        s for s in ADAPTER_SPECS if s.adapter_id is ResourceAdapterId.IMAGE_DIRECTORY
    )
    result = RegistryResourceAdapterExecutor().parse_file(
        absolute_path=path,
        resource_absolute_path=resource_path,
        adapter=adapter,
        role=AssetRole.PAGE,
    )
    assert result.ok is True
    assert result.asset is not None
    assert result.asset.role is AssetRole.PAGE
    assert result.asset.sort_key == path.name
    assert result.asset.title == "第 02 页 & image"
    assert result.resource_title == resource_path.name
    assert result.local_metadata is not None
    assert result.local_metadata.metadata.title == resource_path.name


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
    assert result.local_metadata.cover == cover
