"""SQLAlchemy persistence for ADR 0018 overlay aggregates."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.common import cuid, db_timestamp
from app.models.library import Library
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.library.domain.organization_modes import (
    TargetLibraryOrganizationMode,
    parse_target_organization_mode,
)
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
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
)


class SqlAlchemyLibraryConfigAdapter(LibraryConfigPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        library = self._session.get(Library, library_id)
        if library is None:
            raise LookupError(library_id)
        mode = parse_target_organization_mode(library.organization_mode)
        if not isinstance(mode, TargetLibraryOrganizationMode):
            # Target pipeline rejects AUDIOBOOK; treat as FLAT for safety.
            mode = TargetLibraryOrganizationMode.FLAT
        return LibrarySourceTreeConfig(
            library_id=library.id,
            root_path=Path(library.root_path),
            organization_mode=mode,
            ignore_hidden=bool(library.ignore_hidden),
            ignore_patterns=library.ignore_patterns,
            global_ignore_patterns="",
            min_file_size_bytes=int(library.min_file_size_bytes),
            queue_high_water=500,
            probe_sample_limit=100,
            probe_max_entries=5000,
            probe_max_depth=32,
            probe_time_budget_ms=30_000,
        )

    def source_node_count(self, library_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(LibrarySourceNode)
                .where(LibrarySourceNode.library_id == library_id)
            )
            or 0
        )

    def update_organization_mode(
        self,
        library_id: str,
        mode: TargetLibraryOrganizationMode,
    ) -> None:
        library = self._session.get(Library, library_id)
        if library is None:
            raise LookupError(library_id)
        library.organization_mode = mode.value
        self._session.flush()

    def update_root_path(self, library_id: str, root_path: Path) -> None:
        library = self._session.get(Library, library_id)
        if library is None:
            raise LookupError(library_id)
        library.root_path = str(root_path)
        self._session.flush()

    def root_path_conflicts(
        self, root_path: Path, *, exclude_library_id: str
    ) -> bool:
        normalized = str(root_path.resolve())
        existing = self._session.scalar(
            select(Library.id).where(
                Library.root_path == normalized,
                Library.id != exclude_library_id,
            )
        )
        return existing is not None


class SqlAlchemySourceNodeRepository(SourceNodeRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_path_key(
        self, library_id: str, path_key: str
    ) -> SourceNodeRecord | None:
        row = self._session.scalar(
            select(LibrarySourceNode).where(
                LibrarySourceNode.library_id == library_id,
                LibrarySourceNode.path_key == path_key,
            )
        )
        return None if row is None else self._to_record(row)

    def get(self, source_node_id: str) -> SourceNodeRecord | None:
        row = self._session.get(LibrarySourceNode, source_node_id)
        return None if row is None else self._to_record(row)

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]:
        existing = self.get_by_path_key(library_id, entry.relative_path.path_key)
        if existing is not None:
            return existing, False
        row = LibrarySourceNode(
            id=cuid(),
            library_id=library_id,
            parent_id=parent_id,
            parent_physical_kind="DIRECTORY" if parent_id is not None else None,
            relative_path=entry.relative_path.value,
            path_key=entry.relative_path.path_key,
            name=entry.relative_path.name,
            physical_kind=entry.physical_kind.value,
            observed_size_bytes=entry.observed_size_bytes,
            observed_mtime_ns=entry.observed_mtime_ns,
            observed_at=entry.observed_at,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row), True

    def refresh_observed(
        self,
        source_node_id: str,
        entry: ObservedSourceEntry,
    ) -> SourceNodeRecord:
        row = self._session.get(LibrarySourceNode, source_node_id)
        if row is None:
            raise LookupError(source_node_id)
        row.observed_size_bytes = entry.observed_size_bytes
        row.observed_mtime_ns = entry.observed_mtime_ns
        row.observed_at = entry.observed_at
        self._session.flush()
        return self._to_record(row)

    def list_subtree_ids(self, source_node_id: str) -> tuple[str, ...]:
        root = self._session.get(LibrarySourceNode, source_node_id)
        if root is None:
            return ()
        pending = [root.id]
        collected: list[str] = []
        while pending:
            current = pending.pop()
            collected.append(current)
            children = self._session.scalars(
                select(LibrarySourceNode.id).where(
                    LibrarySourceNode.parent_id == current
                )
            ).all()
            pending.extend(children)
        return tuple(collected)

    def delete_subtree(self, source_node_id: str) -> None:
        ids = self.list_subtree_ids(source_node_id)
        if not ids:
            return
        self._session.execute(
            delete(LibrarySourceNode).where(LibrarySourceNode.id.in_(ids))
        )
        self._session.flush()

    def get_interpretation(
        self, source_node_id: str
    ) -> InterpretationRecord | None:
        row = self._session.get(LibrarySourceNodeInterpretation, source_node_id)
        if row is None:
            return None
        return InterpretationRecord(
            source_node_id=row.source_node_id,
            result=row.result,
            source=row.source,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            reason_code=row.reason_code,
        )

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
    ) -> None:
        row = self._session.get(LibrarySourceNodeInterpretation, source_node_id)
        if row is None:
            row = LibrarySourceNodeInterpretation(source_node_id=source_node_id)
            self._session.add(row)
        row.result = result
        row.source = source
        row.adapter_id = adapter_id
        row.adapter_version = adapter_version
        row.reason_code = reason_code
        row.sample_relative_paths = sample_relative_paths
        row.sample_count = sample_count
        row.max_entries_visited = max_entries_visited
        row.max_depth = max_depth
        row.time_budget_ms = time_budget_ms
        row.termination_reason = termination_reason
        row.recognized_at = recognized_at
        self._session.flush()

    def _to_record(self, row: LibrarySourceNode) -> SourceNodeRecord:
        return SourceNodeRecord(
            id=row.id,
            library_id=row.library_id,
            parent_id=row.parent_id,
            relative_path=row.relative_path,
            path_key=row.path_key,
            name=row.name,
            physical_kind=SourceNodePhysicalKind(row.physical_kind),
            observed_size_bytes=row.observed_size_bytes,
            observed_mtime_ns=row.observed_mtime_ns,
            observed_at=row.observed_at,
        )


class SqlAlchemyBookResourceRepository(BookResourceRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_book(
        self,
        *,
        library_id: str,
        source_node_id: str,
        title: str,
    ) -> str:
        existing = self.get_book_id_for_source_node(source_node_id)
        if existing is not None:
            return existing
        book_id = cuid()
        self._session.add(
            LibraryBook(
                id=book_id,
                library_id=library_id,
                source_node_id=source_node_id,
            )
        )
        self._session.add(
            LibraryBookMetadata(
                book_id=book_id,
                title=title,
                normalized_title=title.casefold(),
            )
        )
        self._session.flush()
        return book_id

    def get_book_id_for_source_node(self, source_node_id: str) -> str | None:
        return self._session.scalar(
            select(LibraryBook.id).where(LibraryBook.source_node_id == source_node_id)
        )

    def get_resource_by_source_node(
        self, source_node_id: str
    ) -> ReadableResourceRecord | None:
        row = self._session.scalar(
            select(LibraryReadableResource).where(
                LibraryReadableResource.source_node_id == source_node_id
            )
        )
        return None if row is None else self._to_resource(row)

    def get_resource(self, resource_id: str) -> ReadableResourceRecord | None:
        row = self._session.get(LibraryReadableResource, resource_id)
        return None if row is None else self._to_resource(row)

    def create_pending_resource(
        self,
        *,
        library_id: str,
        book_id: str,
        source_node_id: str,
        adapter: AdapterIdentity,
        active_import_run_id: str,
    ) -> ReadableResourceRecord:
        row = LibraryReadableResource(
            id=cuid(),
            library_id=library_id,
            book_id=book_id,
            source_node_id=source_node_id,
            adapter_id=adapter.adapter_id,
            adapter_version=adapter.adapter_version,
            media_kind=adapter.media_kind,
            format=adapter.format_label,
            enablement_state=ResourceEnablementState.ENABLED.value,
            import_state=ResourceImportState.PENDING.value,
            active_import_run_id=active_import_run_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_resource(row)

    def cas_set_active_import_run(
        self,
        resource_id: str,
        *,
        expected_active_run_id: str | None,
        new_active_run_id: str | None,
    ) -> bool:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return False
        if row.active_import_run_id != expected_active_run_id:
            return False
        row.active_import_run_id = new_active_run_id
        self._session.flush()
        return True

    def set_enablement(
        self,
        resource_id: str,
        state: ResourceEnablementState,
    ) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            raise LookupError(resource_id)
        row.enablement_state = state.value
        self._session.flush()

    def publish_resource(
        self,
        *,
        resource_id: str,
        published_run_id: str,
        adapter: AdapterIdentity,
        title: str,
    ) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            raise LookupError(resource_id)
        row.published_run_id = published_run_id
        row.import_state = ResourceImportState.READY.value
        row.adapter_id = adapter.adapter_id
        row.adapter_version = adapter.adapter_version
        row.media_kind = adapter.media_kind
        row.format = adapter.format_label
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            self._session.add(
                LibraryReadableResourceMetadata(resource_id=resource_id, title=title)
            )
        else:
            metadata.title = title
        self._session.flush()

    def mark_resource_failed(self, resource_id: str) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return
        row.import_state = ResourceImportState.FAILED.value
        self._session.flush()

    def clear_active_import_run(self, resource_id: str) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return
        row.active_import_run_id = None
        self._session.flush()

    def touch_updated_at(self, resource_id: str) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return
        row.updated_at = db_timestamp()
        self._session.flush()

    def upsert_asset(
        self,
        *,
        library_id: str,
        resource_id: str,
        source_node_id: str,
        published_run_id: str,
        role: AssetRole,
        import_state: AssetImportState,
        sequence_index: int | None,
        sort_key: str | None,
        failure_reason: str | None,
    ) -> str:
        row = self._session.scalar(
            select(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.source_node_id == source_node_id,
            )
        )
        if row is None:
            row = LibraryResourceAsset(
                id=cuid(),
                library_id=library_id,
                resource_id=resource_id,
                source_node_id=source_node_id,
                source_node_physical_kind="REGULAR_FILE",
            )
            self._session.add(row)
        row.published_run_id = published_run_id
        row.role = role.value
        row.import_state = import_state.value
        row.sequence_index = sequence_index
        row.sort_key = sort_key
        row.failure_reason = failure_reason
        self._session.flush()
        return row.id

    def count_ready_assets_for_published_run(
        self, resource_id: str, published_run_id: str
    ) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.published_run_id == published_run_id,
                    LibraryResourceAsset.import_state
                    == AssetImportState.READY.value,
                )
            )
            or 0
        )

    def find_outermost_directory_resource(
        self,
        library_id: str,
        relative_path: str,
    ) -> ReadableResourceRecord | None:
        parts = relative_path.split("/")
        candidates: list[str] = []
        for index in range(1, len(parts)):
            candidates.append("/".join(parts[:index]))
        if not candidates:
            return None
        path_keys = [
            SourceNodeRelativePath(path).path_key for path in candidates
        ]
        nodes = self._session.scalars(
            select(LibrarySourceNode).where(
                LibrarySourceNode.library_id == library_id,
                LibrarySourceNode.path_key.in_(path_keys),
                LibrarySourceNode.physical_kind == "DIRECTORY",
            )
        ).all()
        by_path = {node.relative_path: node for node in nodes}
        for path in candidates:
            node = by_path.get(path)
            if node is None:
                continue
            resource = self.get_resource_by_source_node(node.id)
            if resource is not None:
                return resource
        return None

    def delete_library_overlay_rows(self, library_id: str) -> None:
        self._session.execute(
            delete(LibrarySourceNode).where(LibrarySourceNode.library_id == library_id)
        )
        self._session.flush()

    def delete_assets_for_source_nodes(
        self, source_node_ids: Sequence[str]
    ) -> tuple[str, ...]:
        if not source_node_ids:
            return ()
        rows = self._session.scalars(
            select(LibraryResourceAsset).where(
                LibraryResourceAsset.source_node_id.in_(tuple(source_node_ids))
            )
        ).all()
        resource_ids = tuple({row.resource_id for row in rows})
        self._session.execute(
            delete(LibraryResourceAsset).where(
                LibraryResourceAsset.source_node_id.in_(tuple(source_node_ids))
            )
        )
        self._session.flush()
        return resource_ids

    def reevaluate_ready_after_asset_loss(
        self, resource_ids: Sequence[str]
    ) -> None:
        for resource_id in resource_ids:
            resource = self.get_resource(resource_id)
            if resource is None or resource.published_run_id is None:
                continue
            ready = self.count_ready_assets_for_published_run(
                resource_id, resource.published_run_id
            )
            if ready < 1:
                self.mark_resource_failed(resource_id)

    def cleanup_stale_assets(
        self, resource_id: str, published_run_id: str
    ) -> None:
        self._session.execute(
            delete(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.published_run_id.is_not(None),
                LibraryResourceAsset.published_run_id != published_run_id,
            )
        )
        self._session.flush()

    def _to_resource(self, row: LibraryReadableResource) -> ReadableResourceRecord:
        return ReadableResourceRecord(
            id=row.id,
            library_id=row.library_id,
            book_id=row.book_id,
            source_node_id=row.source_node_id,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            media_kind=row.media_kind,
            format=row.format,
            enablement_state=ResourceEnablementState(row.enablement_state),
            import_state=ResourceImportState(row.import_state),
            published_run_id=row.published_run_id,
            active_import_run_id=row.active_import_run_id,
        )
