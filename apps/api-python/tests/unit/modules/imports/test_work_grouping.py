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
        siblings: tuple[Path, ...] = (),
        *,
        complete: bool = True,
        monitor_root: Path | None = None,
    ) -> None:
        self._identities = identities
        self._siblings = siblings
        self._complete = complete
        self._monitor_root = monitor_root

    def recognize_filename_identity(self, filename: str) -> BookIdentityDTO:
        return self.parse_filename_identity(filename)

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

    def list_sibling_files(self, _path: Path) -> DirectorySiblingSnapshotDTO:
        return DirectorySiblingSnapshotDTO(
            paths=self._siblings,
            complete=self._complete,
        )

    def is_monitor_root(self, path: Path) -> bool:
        return (
            self._monitor_root is not None
            and path.resolve() == self._monitor_root.resolve()
        )


def _preferences() -> ImportPreferencesDTO:
    return ImportPreferencesDTO(
        auto_convert_to_epub=False,
        allowed_extensions=(".epub", ".pdf", ".cbz", ".zip", ".mobi"),
        ignore_patterns="",
    )


def _options(path: Path, *, work_id: str | None = None) -> ImportOptions:
    return ImportOptions(
        source_file_path=path,
        original_name=path.name,
        origin="MANUAL",
        requested_work_id=work_id,
    )


@pytest.mark.parametrize(
    ("file_volume", "sibling_title", "parent_title"),
    [
        (1.0, None, "Collection"),
        (None, "abcdefgxyz", "Collection"),
        (None, None, "abcdefgxyz"),
    ],
)
def test_any_volume_evidence_keeps_file_in_parent_folder_work(
    tmp_path: Path,
    file_volume: float | None,
    sibling_title: str | None,
    parent_title: str,
) -> None:
    parent = tmp_path / "collection"
    source = parent / "abcdefghij.epub"
    sibling = parent / "other.pdf"
    identities = {
        source.name: ("abcdefghij", file_volume),
        "collection.epub": (parent_title, None),
    }
    siblings: tuple[Path, ...] = ()
    if sibling_title is not None:
        identities[sibling.name] = (sibling_title, None)
        siblings = (sibling,)

    decision = resolve_non_audio_work_identity(
        GroupingServices(identities, siblings),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "folder"
    assert decision.title == parent_title
    assert decision.volume_index == file_volume


def test_file_is_standalone_only_when_all_three_conditions_are_met(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "collection"
    source = parent / "abcdefghij.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("abcdefghij", None),
                "collection.epub": ("unrelated", None),
            }
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "standalone"
    assert decision.title == "abcdefghij"
    assert decision.volume_index is None


def test_exactly_fifty_percent_similarity_does_not_count_as_similar(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "collection"
    source = parent / "aaa.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("aaa", None),
                "collection.epub": ("a", None),
            }
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "standalone"


def test_incomplete_sibling_scan_falls_back_to_folder_work(tmp_path: Path) -> None:
    parent = tmp_path / "collection"
    source = parent / "book.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("book", None),
                "collection.epub": ("unrelated", None),
            },
            complete=False,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "folder"


def test_explicit_manual_work_selection_has_priority(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    decision = resolve_non_audio_work_identity(
        GroupingServices({source.name: ("book", 2)}),
        _options(source, work_id="selected-work"),
        _preferences(),
    )

    assert decision.grouping_kind == "explicit"
    assert decision.reused_work_id == "selected-work"


def test_explicit_volume_does_not_scan_large_sibling_directory(tmp_path: Path) -> None:
    parent = tmp_path / "collection"
    source = parent / "book Vol.12.epub"

    class NoSiblingScanServices(GroupingServices):
        def list_sibling_files(self, _path: Path) -> DirectorySiblingSnapshotDTO:
            raise AssertionError("explicit volume grouping must not scan siblings")

    decision = resolve_non_audio_work_identity(
        NoSiblingScanServices(
            {
                source.name: ("book", 12),
                "collection.epub": ("collection", None),
            }
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "folder"
    assert decision.volume_index == 12


def test_direct_monitor_root_file_never_uses_root_as_folder_work(
    tmp_path: Path,
) -> None:
    source = tmp_path / "高桥留美子漫画 犬夜叉_第56卷.mobi"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {source.name: ("高桥留美子漫画 犬夜叉", 56)},
            siblings=(tmp_path / "unrelated.epub",),
            monitor_root=tmp_path,
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "monitor_root_file"
    assert decision.title == "高桥留美子漫画 犬夜叉"
    assert decision.volume_index == 56
    assert decision.grouping_key is not None
    assert decision.grouping_key.startswith("monitor-root-file:")


def test_file_range_uses_range_start_without_parsing_parent_range_as_volume(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "瑞克和莫蒂1-60话 MOBI格式"
    source = parent / "瑞克与莫蒂 - 第006-010话.mobi"
    decision = resolve_non_audio_work_identity(
        GroupingServices(
            {
                source.name: ("瑞克与莫蒂 - 第006-010话", None),
                f"{parent.name}.epub": (parent.name, None),
            }
        ),
        _options(source),
        _preferences(),
    )

    assert decision.grouping_kind == "folder"
    assert decision.title == parent.name
    assert decision.volume_index == 6
