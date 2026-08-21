from __future__ import annotations

from app.modules.library.domain.book_placement import (
    decide_book_anchor_for_resource,
    volumes_root_folder_creates_empty_book_on_discovery,
)
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.source_nodes import SourceNodeRelativePath


def _path(raw: str) -> SourceNodeRelativePath:
    return SourceNodeRelativePath(raw)


def test_flat_always_creates_book_at_resource_node() -> None:
    for relative, is_dir in (
        ("Novel.epub", False),
        ("Series/vol1.epub", False),
        ("Audiobook", True),
        ("Nested/Dir", True),
    ):
        decision = decide_book_anchor_for_resource(
            organization_mode=TargetLibraryOrganizationMode.FLAT,
            resource_relative_path=_path(relative),
            resource_is_directory=is_dir,
        )
        assert decision.create_new_book_at_source_node is True
        assert decision.volumes_root_folder_relative_path is None


def test_volumes_root_file_creates_book_at_file() -> None:
    decision = decide_book_anchor_for_resource(
        organization_mode=TargetLibraryOrganizationMode.VOLUMES,
        resource_relative_path=_path("standalone.epub"),
        resource_is_directory=False,
    )
    assert decision.create_new_book_at_source_node is True
    assert decision.volumes_root_folder_relative_path is None


def test_volumes_nested_resource_anchors_to_root_folder() -> None:
    decision = decide_book_anchor_for_resource(
        organization_mode=TargetLibraryOrganizationMode.VOLUMES,
        resource_relative_path=_path("Series/vol1.epub"),
        resource_is_directory=False,
    )
    assert decision.create_new_book_at_source_node is False
    assert decision.volumes_root_folder_relative_path == "Series"


def test_volumes_root_directory_resource_anchors_to_itself_as_folder() -> None:
    decision = decide_book_anchor_for_resource(
        organization_mode=TargetLibraryOrganizationMode.VOLUMES,
        resource_relative_path=_path("Audiobook"),
        resource_is_directory=True,
    )
    assert decision.create_new_book_at_source_node is False
    assert decision.volumes_root_folder_relative_path == "Audiobook"


def test_empty_book_on_volumes_root_directory_discovery() -> None:
    assert (
        volumes_root_folder_creates_empty_book_on_discovery(
            TargetLibraryOrganizationMode.VOLUMES,
            is_root_child_directory=True,
        )
        is True
    )
    assert (
        volumes_root_folder_creates_empty_book_on_discovery(
            TargetLibraryOrganizationMode.VOLUMES,
            is_root_child_directory=False,
        )
        is False
    )
    assert (
        volumes_root_folder_creates_empty_book_on_discovery(
            TargetLibraryOrganizationMode.FLAT,
            is_root_child_directory=True,
        )
        is False
    )
