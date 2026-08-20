from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.imports.application.dto import BookIdentityDTO, ImportOptions
from app.modules.imports.application.path_metadata import (
    resolve_non_audio_path_metadata,
)


class FilenameMetadataServices:
    def __init__(self, identity: BookIdentityDTO) -> None:
        self.identity = identity
        self.filenames: list[str] = []

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO:
        self.filenames.append(filename)
        return self.identity


def _identity(
    *, title: str, volume_index: float | None, author: str = "未知作者"
) -> BookIdentityDTO:
    return BookIdentityDTO(
        title=title,
        author=author,
        volume_index=volume_index,
        source="regex",
        confidence=0.9,
        logical_path="filename",
    )


@pytest.mark.parametrize(
    ("filename", "work_title", "volume_index"),
    [
        ("作品 (3).cbz", "作品", 3.0),
        ("Vol.4 作品.epub", "作品", 4.0),
        ("作品_005.epub", "作品", 5.0),
        ("作品 6.epub", "作品", 6.0),
    ],
)
def test_filename_metadata_preserves_release_title_and_parsed_index(
    tmp_path: Path,
    filename: str,
    work_title: str,
    volume_index: float,
) -> None:
    source = tmp_path / "ignored-parent" / filename
    services = FilenameMetadataServices(
        _identity(title=work_title, volume_index=volume_index)
    )

    resolution = resolve_non_audio_path_metadata(
        services,
        ImportOptions(
            source_file_path=source,
            original_name=filename,
            origin="SCAN",
        ),
    )

    assert services.filenames == [filename]
    assert resolution.identity.title == work_title
    assert resolution.metadata.title == work_title
    assert resolution.metadata.volume_title == source.stem
    assert resolution.metadata.volume_index == volume_index
    assert resolution.metadata.series_name is None


def test_filename_range_uses_start_without_reading_directory_neighbors(
    tmp_path: Path,
) -> None:
    filename = "作品 第7-9卷.epub"
    services = FilenameMetadataServices(
        _identity(title="作品", volume_index=None, author="作者")
    )

    resolution = resolve_non_audio_path_metadata(
        services,
        ImportOptions(
            source_file_path=tmp_path / "任意目录" / filename,
            original_name=filename,
            origin="SCAN",
        ),
    )

    assert resolution.identity.volume_index == 7.0
    assert resolution.metadata.authors == ("作者",)


def test_filename_metadata_does_not_expose_grouping_contract(tmp_path: Path) -> None:
    filename = "作品.epub"
    resolution = resolve_non_audio_path_metadata(
        FilenameMetadataServices(_identity(title="作品", volume_index=None)),
        ImportOptions(
            source_file_path=tmp_path / "系列" / filename,
            original_name=filename,
            origin="SCAN",
        ),
    )

    raw_metadata = resolution.identity.raw_metadata()
    assert "groupingKind" not in raw_metadata
    assert "groupingKey" not in raw_metadata
