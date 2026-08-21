"""Library-owned ports for source-tree management use cases.

Kept in library so manage commands do not deep-import imports application ports.
Infrastructure adapters satisfy these Protocols structurally.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol

from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.readable_resource_states import ResourceEnablementState


class ManagedSourceNodeView(Protocol):
    @property
    def library_id(self) -> str: ...


class ManagedResourceView(Protocol):
    @property
    def library_id(self) -> str: ...


class ManageUnitOfWorkPort(Protocol):
    def release_before_io(self) -> None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def rollback(self) -> None: ...


class ManageLibraryConfigPort(Protocol):
    def update_organization_mode(
        self,
        library_id: str,
        mode: TargetLibraryOrganizationMode,
    ) -> None: ...

    def update_root_path(self, library_id: str, root_path: Path) -> None: ...

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool: ...


class ManageFilesystemPort(Protocol):
    def path_is_readable_directory(self, path: Path) -> bool: ...


class ManageSourceNodePort(Protocol):
    def get(self, source_node_id: str) -> ManagedSourceNodeView | None: ...

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]: ...

    def delete_subtree(self, source_node_id: str) -> None: ...


class ManageBookResourcePort(Protocol):
    def get_resource(self, resource_id: str) -> ManagedResourceView | None: ...

    def set_enablement(
        self,
        resource_id: str,
        state: ResourceEnablementState,
    ) -> None: ...

    def delete_library_overlay_rows(self, library_id: str) -> None: ...

    def delete_assets_for_source_nodes(
        self, source_node_ids: Sequence[str]
    ) -> tuple[str, ...]: ...

    def reevaluate_ready_after_asset_loss(self, resource_ids: Sequence[str]) -> None: ...


class ManageLibraryImportTasksPort(Protocol):
    """Library-scoped target import-task maintenance for management use cases."""

    def replace_with_fresh_library_scan(self, library_id: str) -> None:
        """Delete every target task for the library and enqueue SCAN_LIBRARY."""
        ...

    def delete_tasks_for_source_nodes(
        self, source_node_ids: Sequence[str]
    ) -> None:
        """Delete CONTINUE_SOURCE / IMPORT_ASSET tasks keyed by source nodes."""
        ...


class ManagePipelineLogPort(Protocol):
    def emit(
        self,
        event: str,
        *,
        library_id: str | None = None,
        resource_id: str | None = None,
        task_id: str | None = None,
        stage: str | None = None,
        outcome: str | None = None,
    ) -> None: ...
