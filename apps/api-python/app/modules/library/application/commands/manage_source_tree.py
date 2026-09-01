"""Management use cases: delete, mode switch, relocate, enable/disable."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.authorization import AuthorizationContext
from app.modules.library.application.commands.manage_ports import (
    ManageBookResourcePort,
    ManageFilesystemPort,
    ManageLibraryConfigPort,
    ManageLibraryImportTasksPort,
    ManagePipelineLogPort,
    ManageSourceDeletionFilesystemPort,
    ManageSourceNodePort,
    ManageUnitOfWorkPort,
)
from app.modules.library.domain.organization_modes import (
    OrganizationModeViolationCode,
    parse_target_organization_mode,
)
from app.modules.library.domain.readable_resource_states import ResourceEnablementState


@dataclass(frozen=True, slots=True)
class ManagementResult:
    ok: bool
    code: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteBookSourcesResult:
    ok: bool
    deleted_book_ids: tuple[str, ...] = ()
    code: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteBookSourcesCommand:
    context: AuthorizationContext
    book_ids: tuple[str, ...]


class SourceFileDeletionError(RuntimeError):
    pass


class DeleteSourceNode:
    _DEFAULT_ASSET_CLEANUP_BATCH_SIZE = 200
    _DEFAULT_TASK_BATCH_SIZE = 500
    _DEFAULT_SOURCE_NODE_BATCH_SIZE = 500

    def __init__(
        self,
        *,
        source_nodes: ManageSourceNodePort,
        books_resources: ManageBookResourcePort,
        import_tasks: ManageLibraryImportTasksPort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
        asset_cleanup_batch_size: int = _DEFAULT_ASSET_CLEANUP_BATCH_SIZE,
        task_batch_size: int = _DEFAULT_TASK_BATCH_SIZE,
        source_node_batch_size: int = _DEFAULT_SOURCE_NODE_BATCH_SIZE,
    ) -> None:
        if asset_cleanup_batch_size < 1:
            raise ValueError("asset_cleanup_batch_size must be positive")
        if task_batch_size < 1:
            raise ValueError("task_batch_size must be positive")
        if source_node_batch_size < 1:
            raise ValueError("source_node_batch_size must be positive")
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._import_tasks = import_tasks
        self._uow = uow
        self._log = log
        self._asset_cleanup_batch_size = asset_cleanup_batch_size
        self._task_batch_size = task_batch_size
        self._source_node_batch_size = source_node_batch_size

    def execute(self, source_node_id: str) -> ManagementResult:
        try:
            with self._uow.transaction():
                node = self._source_nodes.get(source_node_id)
                if node is None:
                    return ManagementResult(ok=False, code="SOURCE_NODE_NOT_FOUND")
                library_id = node.library_id
                subtree = self._source_nodes.list_subtree_ids(source_node_id)

            for offset in range(0, len(subtree), self._asset_cleanup_batch_size):
                batch = subtree[offset : offset + self._asset_cleanup_batch_size]
                with self._uow.transaction():
                    affected_resources = (
                        self._books_resources.delete_assets_for_source_nodes(batch)
                    )
                    self._books_resources.reevaluate_ready_after_asset_loss(
                        affected_resources
                    )

            for offset in range(0, len(subtree), self._task_batch_size):
                batch = subtree[offset : offset + self._task_batch_size]
                with self._uow.transaction():
                    self._import_tasks.delete_tasks_for_source_nodes(batch)

            descendants = tuple(reversed(subtree[1:]))
            for offset in range(0, len(descendants), self._source_node_batch_size):
                batch = descendants[offset : offset + self._source_node_batch_size]
                with self._uow.transaction():
                    self._source_nodes.delete_nodes(batch)

            with self._uow.transaction():
                if self._source_nodes.get(source_node_id) is None:
                    return ManagementResult(ok=False, code="SOURCE_NODE_NOT_FOUND")
                self._source_nodes.delete_nodes((source_node_id,))
            self._log.emit(
                "source_tree.delete.completed",
                library_id=library_id,
                stage="delete",
                outcome="ok",
            )
            return ManagementResult(ok=True)
        except Exception:
            self._uow.rollback()
            raise


class DeleteBookSources:
    """Delete original sources first, then remove their library topology."""

    def __init__(
        self,
        *,
        filesystem: ManageSourceDeletionFilesystemPort,
        source_nodes: ManageSourceNodePort,
        books_resources: ManageBookResourcePort,
        import_tasks: ManageLibraryImportTasksPort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
    ) -> None:
        self._filesystem = filesystem
        self._source_nodes = source_nodes
        self._books_resources = books_resources
        self._import_tasks = import_tasks
        self._uow = uow
        self._log = log

    def execute(self, command: DeleteBookSourcesCommand) -> DeleteBookSourcesResult:
        unique_book_ids = tuple(dict.fromkeys(command.book_ids))
        targets = self._books_resources.source_targets_for_books(unique_book_ids)
        if len(targets) != len(unique_book_ids):
            return DeleteBookSourcesResult(ok=False, code="BOOK_NOT_FOUND")
        allowed_library_ids = set(command.context.library_ids)
        if not command.context.is_admin and any(
            target.library_id not in allowed_library_ids for target in targets
        ):
            return DeleteBookSourcesResult(ok=False, code="BOOK_NOT_FOUND")

        try:
            self._uow.release_before_io()
            for target in targets:
                try:
                    self._filesystem.delete_source(
                        root=target.library_root,
                        relative_path=target.relative_path,
                        physical_kind=target.physical_kind,
                    )
                except (OSError, ValueError) as error:
                    raise SourceFileDeletionError(target.book_id) from error

            with self._uow.transaction():
                for target in targets:
                    node = self._source_nodes.get(target.source_node_id)
                    if node is None:
                        continue
                    subtree = self._source_nodes.list_subtree_ids(target.source_node_id)
                    affected_resources = (
                        self._books_resources.delete_assets_for_source_nodes(subtree)
                    )
                    self._import_tasks.delete_tasks_for_source_nodes(subtree)
                    self._source_nodes.delete_subtree(target.source_node_id)
                    self._books_resources.reevaluate_ready_after_asset_loss(
                        affected_resources
                    )
            for target in targets:
                self._log.emit(
                    "book_source.delete.completed",
                    library_id=target.library_id,
                    stage="delete_source",
                    outcome="ok",
                )
            return DeleteBookSourcesResult(
                ok=True,
                deleted_book_ids=unique_book_ids,
            )
        except Exception:
            self._uow.rollback()
            raise


class ChangeLibraryOrganizationMode:
    def __init__(
        self,
        *,
        libraries: ManageLibraryConfigPort,
        books_resources: ManageBookResourcePort,
        import_tasks: ManageLibraryImportTasksPort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._books_resources = books_resources
        self._import_tasks = import_tasks
        self._uow = uow
        self._log = log

    def execute(self, library_id: str, mode: str) -> ManagementResult:
        parsed = parse_target_organization_mode(mode)
        if isinstance(parsed, OrganizationModeViolationCode):
            return ManagementResult(ok=False, code=parsed.value)
        try:
            with self._uow.transaction():
                # Clear overlay → update mode → replace tasks with fresh scan.
                self._books_resources.delete_library_overlay_rows(library_id)
                self._libraries.update_organization_mode(library_id, parsed)
                self._import_tasks.replace_with_fresh_library_scan(library_id)
            self._log.emit(
                "source_tree.organization_mode.changed",
                library_id=library_id,
                stage="mode_switch",
                outcome="ok",
            )
            return ManagementResult(ok=True)
        except Exception:
            self._uow.rollback()
            raise


class RelocateLibraryRoot:
    def __init__(
        self,
        *,
        libraries: ManageLibraryConfigPort,
        filesystem: ManageFilesystemPort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
    ) -> None:
        self._libraries = libraries
        self._filesystem = filesystem
        self._uow = uow
        self._log = log

    def execute(self, library_id: str, new_root: Path) -> ManagementResult:
        try:
            resolved = new_root.resolve()
            self._uow.release_before_io()
            if not self._filesystem.path_is_readable_directory(resolved):
                return ManagementResult(ok=False, code="ROOT_NOT_READABLE")
            with self._uow.transaction():
                if self._libraries.root_path_conflicts(
                    resolved, exclude_library_id=library_id
                ):
                    return ManagementResult(ok=False, code="ROOT_CONFLICT")
                self._libraries.update_root_path(library_id, resolved)
            self._log.emit(
                "source_tree.root.relocated",
                library_id=library_id,
                stage="relocate",
                outcome="ok",
            )
            return ManagementResult(ok=True)
        except Exception:
            self._uow.rollback()
            raise


class EnableReadableResource:
    def __init__(
        self,
        *,
        books_resources: ManageBookResourcePort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
    ) -> None:
        self._books_resources = books_resources
        self._uow = uow
        self._log = log

    def execute(self, resource_id: str) -> ManagementResult:
        try:
            with self._uow.transaction():
                resource = self._books_resources.get_resource(resource_id)
                if resource is None:
                    return ManagementResult(ok=False, code="RESOURCE_NOT_FOUND")
                library_id = resource.library_id
                self._books_resources.set_enablement(
                    resource_id, ResourceEnablementState.ENABLED
                )
            self._log.emit(
                "readable_resource.enablement.enabled",
                library_id=library_id,
                resource_id=resource_id,
                stage="enablement",
                outcome="ok",
            )
            return ManagementResult(ok=True)
        except Exception:
            self._uow.rollback()
            raise


class DisableReadableResource:
    def __init__(
        self,
        *,
        books_resources: ManageBookResourcePort,
        uow: ManageUnitOfWorkPort,
        log: ManagePipelineLogPort,
    ) -> None:
        self._books_resources = books_resources
        self._uow = uow
        self._log = log

    def execute(self, resource_id: str) -> ManagementResult:
        try:
            with self._uow.transaction():
                resource = self._books_resources.get_resource(resource_id)
                if resource is None:
                    return ManagementResult(ok=False, code="RESOURCE_NOT_FOUND")
                library_id = resource.library_id
                self._books_resources.set_enablement(
                    resource_id, ResourceEnablementState.DISABLED
                )
            self._log.emit(
                "readable_resource.enablement.disabled",
                library_id=library_id,
                resource_id=resource_id,
                stage="enablement",
                outcome="ok",
            )
            return ManagementResult(ok=True)
        except Exception:
            self._uow.rollback()
            raise
