"""FLAT / VOLUMES book-anchor placement for newly recognized resources."""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.source_nodes import SourceNodeRelativePath


@dataclass(frozen=True, slots=True)
class BookAnchorDecision:
    """Where a newly recognized Resource should attach as a Book."""

    create_new_book_at_source_node: bool
    volumes_root_folder_relative_path: str | None


def decide_book_anchor_for_resource(
    *,
    organization_mode: TargetLibraryOrganizationMode,
    resource_relative_path: SourceNodeRelativePath,
    resource_is_directory: bool,
) -> BookAnchorDecision:
    """Return book placement without consulting siblings or the filesystem."""

    if organization_mode is TargetLibraryOrganizationMode.FLAT:
        return BookAnchorDecision(
            create_new_book_at_source_node=True,
            volumes_root_folder_relative_path=None,
        )

    root_segment = resource_relative_path.value.split("/", 1)[0]
    if resource_relative_path.is_root_child and not resource_is_directory:
        return BookAnchorDecision(
            create_new_book_at_source_node=True,
            volumes_root_folder_relative_path=None,
        )
    return BookAnchorDecision(
        create_new_book_at_source_node=False,
        volumes_root_folder_relative_path=root_segment,
    )


def volumes_root_folder_creates_empty_book_on_discovery(
    organization_mode: TargetLibraryOrganizationMode,
    *,
    is_root_child_directory: bool,
) -> bool:
    return (
        organization_mode is TargetLibraryOrganizationMode.VOLUMES
        and is_root_child_directory
    )
