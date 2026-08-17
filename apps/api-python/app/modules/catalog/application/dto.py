"""Typed application DTOs for the current Library capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.modules.catalog.domain.access import GrantLevel
from app.modules.catalog.domain.ignore_rules import IgnoreRule
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    LibraryHealth,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison


@dataclass(frozen=True, slots=True)
class LibrarySummary:
    id: str
    name: str
    organization_mode: OrganizationMode
    control_state: LibraryControlState
    observed_health: LibraryHealth
    config_revision: int
    grant_level: GrantLevel
    topology_version: int
    path_comparison: PathComparison
    write_policy: WritePolicy
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LibraryAdminDetails(LibrarySummary):
    root_path: str
    root_path_key: str


@dataclass(frozen=True, slots=True)
class LibraryPage:
    items: tuple[LibrarySummary, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class LibraryGrantView:
    user_id: str
    library_id: str
    level: GrantLevel
    scope_epoch: int


@dataclass(frozen=True, slots=True)
class LibraryGrantPage:
    items: tuple[LibraryGrantView, ...]
    next_cursor: str | None


def summary_from_library(library: Library, grant_level: GrantLevel) -> LibrarySummary:
    return LibrarySummary(
        id=library.id,
        name=library.name,
        organization_mode=library.organization_mode,
        control_state=library.control_state,
        observed_health=library.observed_health,
        config_revision=library.config_revision,
        grant_level=grant_level,
        topology_version=library.topology_version,
        path_comparison=library.path_comparison,
        write_policy=library.write_policy,
        created_at=library.created_at,
        updated_at=library.updated_at,
    )


def admin_details_from_library(
    library: Library, grant_level: GrantLevel
) -> LibraryAdminDetails:
    summary = summary_from_library(library, grant_level)
    return LibraryAdminDetails(
        id=summary.id,
        name=summary.name,
        organization_mode=summary.organization_mode,
        control_state=summary.control_state,
        observed_health=summary.observed_health,
        config_revision=summary.config_revision,
        grant_level=summary.grant_level,
        topology_version=summary.topology_version,
        path_comparison=summary.path_comparison,
        write_policy=summary.write_policy,
        created_at=summary.created_at,
        updated_at=summary.updated_at,
        root_path=library.root.canonical_path,
        root_path_key=library.root.root_path_key,
    )


@dataclass(frozen=True, slots=True)
class IgnoreRulesResult:
    library_id: str
    config_revision: int
    rules: tuple[IgnoreRule, ...]
