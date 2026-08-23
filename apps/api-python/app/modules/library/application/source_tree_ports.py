"""Library-owned ports and DTOs for SourceNode / Book / ReadableResource persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.contracts.publication_metadata import PublicationMetadata
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import (
    AssetImportState,
    AssetRole,
    ResourceEnablementState,
    ResourceImportState,
)
from app.modules.library.domain.source_nodes import (
    SourceNodePhysicalKind,
    SourceNodeRelativePath,
)


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    """Neutral adapter identity for library persistence (no imports.domain coupling)."""

    adapter_id: str
    adapter_version: str
    media_kind: str
    format_label: str


@dataclass(frozen=True, slots=True)
class ResourceNavigationUnitInput:
    """Parser-owned navigation data materialized for one Resource asset."""

    unit_type: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    size: int | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class LibrarySourceTreeConfig:
    library_id: str
    root_path: Path
    organization_mode: TargetLibraryOrganizationMode
    ignore_hidden: bool
    ignore_patterns: str | None
    global_ignore_patterns: str
    probe_sample_limit: int
    probe_max_entries: int
    probe_max_depth: int
    probe_time_budget_ms: int


@dataclass(frozen=True, slots=True)
class ObservedSourceEntry:
    relative_path: SourceNodeRelativePath
    physical_kind: SourceNodePhysicalKind
    observed_size_bytes: int | None
    observed_mtime_ns: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class SourceNodeRecord:
    id: str
    library_id: str
    parent_id: str | None
    relative_path: str
    path_key: str
    name: str
    physical_kind: SourceNodePhysicalKind
    observed_size_bytes: int | None
    observed_mtime_ns: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class InterpretationRecord:
    source_node_id: str
    result: str
    source: str
    adapter_id: str | None
    adapter_version: str | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class ReadableResourceRecord:
    id: str
    library_id: str
    book_id: str
    source_node_id: str
    adapter_id: str
    adapter_version: str
    media_kind: str
    format: str
    enablement_state: ResourceEnablementState
    import_state: ResourceImportState


class LibraryConfigPort(Protocol):
    def get_library(self, library_id: str) -> LibrarySourceTreeConfig: ...

    def source_node_count(self, library_id: str) -> int: ...

    def update_organization_mode(
        self,
        library_id: str,
        mode: TargetLibraryOrganizationMode,
    ) -> None: ...

    def update_root_path(self, library_id: str, root_path: Path) -> None: ...

    def root_path_conflicts(
        self, root_path: Path, *, exclude_library_id: str
    ) -> bool: ...


class SourceNodeRepositoryPort(Protocol):
    def get_by_path_key(
        self, library_id: str, path_key: str
    ) -> SourceNodeRecord | None: ...

    def get(self, source_node_id: str) -> SourceNodeRecord | None: ...

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]: ...

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]: ...

    def delete_subtree(self, source_node_id: str) -> None: ...

    def get_interpretation(
        self, source_node_id: str
    ) -> InterpretationRecord | None: ...

    def upsert_interpretation(
        self,
        *,
        source_node_id: str,
        result: str,
        source: str,
        adapter_id: str | None,
        adapter_version: str | None,
        reason_code: str | None,
        sample_relative_paths: str | None,
        sample_count: int | None,
        max_entries_visited: int | None,
        max_depth: int | None,
        time_budget_ms: int | None,
        termination_reason: str | None,
        recognized_at: datetime | None,
    ) -> None: ...


class BookResourceRepositoryPort(Protocol):
    def ensure_book(
        self,
        *,
        library_id: str,
        source_node_id: str,
        title: str,
    ) -> str: ...

    def get_book_id_for_source_node(self, source_node_id: str) -> str | None: ...

    def get_resource_by_source_node(
        self, source_node_id: str
    ) -> ReadableResourceRecord | None: ...

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None: ...

    def create_pending_resource(
        self,
        *,
        library_id: str,
        book_id: str,
        source_node_id: str,
        adapter: AdapterIdentity,
    ) -> ReadableResourceRecord: ...

    def set_enablement(
        self,
        resource_id: str,
        state: ResourceEnablementState,
    ) -> None: ...

    def mark_resource_ready(
        self,
        *,
        resource_id: str,
        title: str | None = None,
    ) -> None: ...

    def set_resource_page_count(self, resource_id: str, page_count: int) -> None: ...

    def apply_local_metadata(
        self,
        *,
        resource_id: str,
        metadata: PublicationMetadata,
        cover_path: str | None = None,
    ) -> None: ...

    def clear_local_cover(self, *, resource_id: str, expected_path: str) -> None: ...

    def mark_resource_failed(self, resource_id: str) -> None: ...

    def upsert_asset(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        role: AssetRole,
        import_state: AssetImportState,
        sequence_index: int | None,
        sort_key: str | None,
        failure_reason: str | None,
    ) -> str: ...

    def count_ready_assets(self, resource_id: str) -> int: ...

    def replace_navigation_units(
        self,
        *,
        resource_id: str,
        asset_id: str,
        units: Sequence[ResourceNavigationUnitInput],
    ) -> None: ...

    def find_outermost_directory_resource(
        self,
        library_id: str,
        relative_path: str,
    ) -> ReadableResourceRecord | None: ...

    def delete_library_overlay_rows(self, library_id: str) -> None: ...

    def delete_assets_for_source_nodes(
        self, source_node_ids: Sequence[str]
    ) -> tuple[str, ...]: ...

    def reevaluate_ready_after_asset_loss(
        self, resource_ids: Sequence[str]
    ) -> None: ...
