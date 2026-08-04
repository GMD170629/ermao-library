from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    DirectorySiblingSnapshotDTO,
    ImportOptions,
    ImportPreferencesDTO,
)
from app.modules.imports.application.work_grouping import (
    resolve_non_audio_work_identity,
)


class GroupingServices:
    def __init__(
        self,
        identities: dict[str, tuple[str, float | None]],
        *,
        monitor_root: Path,
        siblings: tuple[Path, ...] = (),
        authors: dict[str, str] | None = None,
    ) -> None:
        self._identities = identities
        self._monitor_root = monitor_root
        self._siblings = siblings
        self._authors = authors or {}

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO:
        identity = self.parse_filename_identity(filename)
        return BookIdentityDTO(
            title=identity.title,
            author=self._authors.get(filename, identity.author),
            volume_index=identity.volume_index,
            source=identity.source,
            confidence=identity.confidence,
            logical_path=identity.logical_path,
        )

    def parse_filename_identity(self, filename: str) -> BookIdentityDTO:
        title, volume_index = self._identities[filename]
        return BookIdentityDTO(
            title=title,
            author="未知作者",
            volume_index=volume_index,
            source="regex",
            confidence=0.9,
            logical_path=filename,
        )

    def monitor_root_path(self, monitor_folder_id: str | None) -> Path | None:
        return self._monitor_root if monitor_folder_id == "monitor" else None

    def list_sibling_files(self, _path: Path) -> DirectorySiblingSnapshotDTO:
        return DirectorySiblingSnapshotDTO(paths=self._siblings, complete=True)


def _preferences() -> ImportPreferencesDTO:
    return ImportPreferencesDTO(
        auto_convert_to_epub=False,
        allowed_extensions=(
            ".epub",
            ".pdf",
            ".cbz",
            ".zip",
            ".mobi",
            ".txt",
        ),
        ignore_patterns="",
    )


def _options(
    path: Path,
    *,
    media_kind_policy: str = "MIXED",
) -> ImportOptions:
    return ImportOptions(
        source_file_path=path,
        original_name=path.name,
        origin="MONITOR_FOLDER",
        monitor_folder_id="monitor",
        media_kind_policy=media_kind_policy,
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
def test_root_file_preserves_release_title_and_uses_parsed_work_and_volume(
    tmp_path: Path,
    filename: str,
    work_title: str,
    volume_index: float,
) -> None:
    source = tmp_path / filename
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {filename: (work_title, volume_index)},
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "monitor_root_file"
    assert decision.metadata.title == work_title
    assert decision.metadata.volume_title == source.stem
    assert decision.metadata.volume_index == volume_index
    assert decision.metadata.series_name is None


def test_nested_explicit_volume_uses_immediate_parent_without_sibling_scan(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "鬼吹灯"
    source = parent / "鬼吹灯1.epub"

    class NoSiblingScanServices(GroupingServices):
        def list_sibling_files(self, _path: Path) -> DirectorySiblingSnapshotDTO:
            raise AssertionError("explicit volume must not scan siblings")

    decision = resolve_non_audio_work_identity(
        NoSiblingScanServices(
            {
                source.name: ("鬼吹灯", 1.0),
                f"{parent.name}.epub": ("鬼吹灯", None),
            },
            monitor_root=tmp_path,
            authors={f"{parent.name}.epub": "天下霸唱"},
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "folder"
    assert decision.metadata.title == "鬼吹灯"
    assert decision.metadata.volume_title == "鬼吹灯1"
    assert decision.metadata.volume_index == 1.0
    assert decision.metadata.authors == ("天下霸唱",)
    assert decision.metadata.series_name == "鬼吹灯"


def test_root_file_without_volume_uses_filename_for_work_and_volume_title(
    tmp_path: Path,
) -> None:
    source = tmp_path / "精绝古城.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {source.name: ("精绝古城", None)},
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.metadata.title == "精绝古城"
    assert decision.metadata.volume_title == "精绝古城"
    assert decision.metadata.volume_index is None


def test_nested_file_uses_parent_when_parent_similarity_is_greater_than_half(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "鬼吹灯"
    source = parent / "鬼吹灯 精绝古城.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("鬼吹灯", None),
                f"{parent.name}.epub": ("鬼吹灯", None),
            },
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "folder"
    assert decision.metadata.title == "鬼吹灯"
    assert decision.metadata.volume_title == "鬼吹灯 精绝古城"
    assert decision.metadata.series_name == "鬼吹灯"


def test_exactly_fifty_percent_similarity_does_not_select_parent(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "a"
    source = parent / "aaa.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("aaa", None),
                f"{parent.name}.epub": ("a", None),
            },
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "standalone"
    assert decision.metadata.title == "aaa"


def test_same_default_media_family_sibling_can_select_parent(tmp_path: Path) -> None:
    parent = tmp_path / "合集"
    source = parent / "current.epub"
    sibling = parent / "related.mobi"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("shared title", None),
                f"{parent.name}.epub": ("合集", None),
                sibling.name: ("shared title", None),
            },
            monitor_root=tmp_path,
            siblings=(sibling,),
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "folder"
    assert decision.metadata.title == "合集"


def test_default_ebook_and_comic_siblings_cannot_provide_evidence(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "合集"
    source = parent / "current.epub"
    sibling = parent / "related.zip"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("shared title", None),
                f"{parent.name}.epub": ("合集", None),
            },
            monitor_root=tmp_path,
            siblings=(sibling,),
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "standalone"
    assert decision.metadata.title == "shared title"


def test_forced_media_policy_allows_supported_formats_to_provide_evidence(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "合集"
    source = parent / "current.epub"
    sibling = parent / "related.zip"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("shared title", None),
                f"{parent.name}.epub": ("合集", None),
                sibling.name: ("shared title", None),
            },
            monitor_root=tmp_path,
            siblings=(sibling,),
        ),
        _options(source, media_kind_policy="EBOOK"),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "folder"
    assert decision.metadata.title == "合集"


def test_irrelevant_siblings_are_filtered_before_filename_parsing(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "合集"
    source = parent / "current.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("current", None),
                f"{parent.name}.epub": ("unrelated", None),
            },
            monitor_root=tmp_path,
            siblings=(
                parent / "metadata.opf",
                parent / "cover.jpg",
                parent / ".current.epub.tmp",
                parent / "track.mp3",
            ),
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "standalone"


def test_file_range_uses_range_start_and_parent_as_work(tmp_path: Path) -> None:
    parent = tmp_path / "瑞克和莫蒂"
    source = parent / "瑞克与莫蒂 - 第006-010话.mobi"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("瑞克与莫蒂 - 第006-010话", None),
                f"{parent.name}.mobi": (parent.name, None),
            },
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.identity.grouping_kind == "folder"
    assert decision.metadata.title == "瑞克和莫蒂"
    assert decision.metadata.volume_title == "瑞克与莫蒂 - 第006-010话"
    assert decision.metadata.volume_index == 6.0
