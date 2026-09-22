"""SQLAlchemy persistence for ADR 0018 overlay aggregates."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.contracts.local_metadata_snapshot import (
    LocalMetadataObservation,
    decode_observations,
    encode_observations,
    merge_observations,
)
from app.contracts.publication_metadata import PublicationMetadata
from app.contracts.reader_safety_policy_generated import (
    READER_SAFETY_AUDIO_PROFILE,
    READER_SAFETY_COMIC_PROFILE,
)
from app.core.exception_diagnostics import record_exception
from app.core.natural_sort import natural_sort_key
from app.infrastructure.local_metadata_policy import SqlAlchemyLocalMetadataPriority
from app.models.common import cuid
from app.models.library import Library, ReadableResourceNavigationUnit
from app.modules.library.application.commands.manage_ports import (
    ManagedBookSourceTarget,
)
from app.modules.library.application.metadata_ownership import protected_fields
from app.modules.library.application.source_browser import (
    SourceLocation,
    SourceNodePage,
)
from app.modules.library.application.source_tree_ports import (
    AdapterIdentity,
    BookResourceRepositoryPort,
    DirectoryAssetResult,
    DirectoryImportMember,
    InterpretationRecord,
    LibraryConfigPort,
    LibrarySourceTreeConfig,
    ObservedSourceEntry,
    ReadableResourceRecord,
    ResourceAssetMetadataInput,
    ResourceCoverState,
    ResourceNavigationUnitInput,
    SourceNodeRecord,
    SourceNodeRepositoryPort,
)
from app.modules.library.domain.organization_modes import (
    TargetLibraryOrganizationMode,
    parse_target_organization_mode,
)
from app.modules.library.domain.readable_resource_anchors import (
    ReadableResourceAnchorViolationCode,
    ReadableResourceTopologyError,
    audiobook_resource_owns_path,
    is_asset_path_within_resource_scope,
    is_resource_anchor_within_book_scope,
    resource_relative_asset_sort_key,
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
    SourceNodeTopologyError,
    SourceNodeTreeNode,
    SourceNodeViolationCode,
    evaluate_path_key_occupancy,
    validate_source_node_direct_parent,
)
from app.modules.library.infrastructure.publication_navigation import (
    SqlAlchemyLibraryNavigationProjection,
)
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeInterpretation,
)
from app.modules.metadata.public import LocalMetadataCandidate, resolve_local_metadata


class SqlAlchemyLibraryConfigAdapter(LibraryConfigPort):
    def __init__(
        self,
        session: Session,
        *,
        global_ignore_patterns_loader: Callable[[], str] | None = None,
    ) -> None:
        self._session = session
        self._global_ignore_patterns_loader = global_ignore_patterns_loader

    def get_library(self, library_id: str) -> LibrarySourceTreeConfig:
        library = self._session.get(Library, library_id)
        if library is None:
            raise LookupError(library_id)
        mode = parse_target_organization_mode(library.organization_mode)
        if not isinstance(mode, TargetLibraryOrganizationMode):
            raise TypeError(
                f"unsupported library organization mode: {library.organization_mode}"
            )
        return LibrarySourceTreeConfig(
            library_id=library.id,
            root_path=Path(library.root_path),
            organization_mode=mode,
            ignore_hidden=bool(library.ignore_hidden),
            allow_empty_library_cleanup=bool(library.allow_empty_library_cleanup),
            ignore_patterns=library.ignore_patterns,
            global_ignore_patterns=(
                self._global_ignore_patterns_loader()
                if self._global_ignore_patterns_loader is not None
                else ""
            ),
            metadata_priority=SqlAlchemyLocalMetadataPriority(self._session).load(),
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

    def root_path_conflicts(self, root_path: Path, *, exclude_library_id: str) -> bool:
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

    @staticmethod
    def _children_query(library_id: str, parent_id: str | None):
        return (
            select(LibrarySourceNode)
            .where(
                LibrarySourceNode.library_id == library_id,
                LibrarySourceNode.parent_id.is_(None)
                if parent_id is None
                else LibrarySourceNode.parent_id == parent_id,
            )
            .order_by(LibrarySourceNode.path_key.asc(), LibrarySourceNode.id.asc())
        )

    def list_direct_children(
        self, *, library_id: str, parent_id: str | None
    ) -> tuple[SourceNodeRecord, ...]:
        rows = self._session.scalars(self._children_query(library_id, parent_id)).all()
        return tuple(self._to_record(row) for row in rows)

    def page_children(
        self, library_id: str, parent_id: str | None, page: int, page_size: int
    ) -> SourceNodePage:
        query = self._children_query(library_id, parent_id)
        total = int(
            self._session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
            or 0
        )
        rows = self._session.scalars(
            query.offset((page - 1) * page_size).limit(page_size)
        )
        return SourceNodePage(
            tuple(self._to_record(row) for row in rows), total, page, page_size
        )

    def location(
        self, node_id: str, library_ids: frozenset[str]
    ) -> SourceLocation | None:
        row = self._session.execute(
            select(LibrarySourceNode, Library.root_path)
            .execution_options(populate_existing=True)
            .join(Library, Library.id == LibrarySourceNode.library_id)
            .where(
                LibrarySourceNode.id == node_id,
                LibrarySourceNode.library_id.in_(library_ids),
            )
        ).first()
        return SourceLocation(self._to_record(row[0]), Path(row[1])) if row else None

    def reconcile_batch(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entries: tuple[ObservedSourceEntry, ...],
    ) -> tuple[tuple[SourceNodeRecord, bool, bool], ...]:
        if not entries or len(entries) > 200:
            raise ValueError("INVALID_NODE_BATCH_SIZE")
        parent = self.get(parent_id) if parent_id is not None else None
        parent_tree = (
            None
            if parent is None
            else SourceNodeTreeNode(
                library_id=parent.library_id,
                relative_path=SourceNodeRelativePath(parent.relative_path),
                physical_kind=parent.physical_kind,
            )
        )
        if parent_id is not None and parent is None:
            raise LookupError(parent_id)
        existing = {
            row.path_key: row
            for row in self._session.scalars(
                select(LibrarySourceNode).where(
                    LibrarySourceNode.library_id == library_id,
                    LibrarySourceNode.path_key.in_(
                        [e.relative_path.path_key for e in entries]
                    ),
                )
            )
        }
        additions = []
        changes = []
        result = []
        for entry in entries:
            violations = validate_source_node_direct_parent(
                node=SourceNodeTreeNode(
                    library_id=library_id,
                    relative_path=entry.relative_path,
                    physical_kind=entry.physical_kind,
                ),
                parent=parent_tree,
            )
            if violations:
                raise SourceNodeTopologyError(
                    violations[0].code, relative_path=violations[0].relative_path
                )
            row = existing.get(entry.relative_path.path_key)
            if row is not None and row.relative_path != entry.relative_path.value:
                result.append((self._to_record(row), False, False))
                continue
            if row is not None and row.physical_kind != entry.physical_kind.value:
                raise SourceNodeTopologyError(
                    SourceNodeViolationCode.PHYSICAL_KIND_CHANGED,
                    relative_path=entry.relative_path.value,
                )
            created = row is None
            changed = (
                row is None
                or row.observed_size_bytes != entry.observed_size_bytes
                or row.observed_mtime_ns != entry.observed_mtime_ns
            )
            if row is None:
                row = LibrarySourceNode(
                    id=cuid(),
                    library_id=library_id,
                    parent_id=parent_id,
                    parent_physical_kind="DIRECTORY" if parent_id else None,
                    relative_path=entry.relative_path.value,
                    path_key=entry.relative_path.path_key,
                    name=entry.relative_path.name,
                    physical_kind=entry.physical_kind.value,
                    observed_size_bytes=entry.observed_size_bytes,
                    observed_mtime_ns=entry.observed_mtime_ns,
                    observed_at=entry.observed_at,
                )
                additions.append(
                    {
                        key: getattr(row, key)
                        for key in (
                            "id",
                            "library_id",
                            "parent_id",
                            "parent_physical_kind",
                            "relative_path",
                            "path_key",
                            "name",
                            "physical_kind",
                            "observed_size_bytes",
                            "observed_mtime_ns",
                            "observed_at",
                        )
                    }
                )
                existing[row.path_key] = row
            elif changed:
                changes.append(
                    {
                        "id": row.id,
                        "observed_size_bytes": entry.observed_size_bytes,
                        "observed_mtime_ns": entry.observed_mtime_ns,
                        "observed_at": entry.observed_at,
                    }
                )
            record = self._to_record(row)
            if changed and not created:
                record = replace(
                    record,
                    observed_size_bytes=entry.observed_size_bytes,
                    observed_mtime_ns=entry.observed_mtime_ns,
                    observed_at=entry.observed_at,
                )
            result.append((record, created, changed))
        for offset in range(0, len(additions), 50):
            self._session.execute(
                sqlite_insert(LibrarySourceNode).values(additions[offset : offset + 50])
            )
        if changes:
            self._session.execute(update(LibrarySourceNode), changes)
        return tuple(result)

    def mark_covered_batch(
        self, node_ids: tuple[str, ...], *, recognized_at: datetime
    ) -> None:
        if not node_ids:
            return
        self._session.execute(
            delete(LibraryReadableResource).where(
                LibraryReadableResource.source_node_id.in_(node_ids)
            )
        )
        for offset in range(0, len(node_ids), 100):
            statement = sqlite_insert(LibrarySourceNodeInterpretation).values(
                [
                    {
                        "source_node_id": node_id,
                        "result": "NODE_ONLY",
                        "source": "AUTO",
                        "reason_code": "COVERED_BY_OUTER_DIRECTORY_RESOURCE",
                        "recognized_at": recognized_at,
                    }
                    for node_id in node_ids[offset : offset + 100]
                ]
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[LibrarySourceNodeInterpretation.source_node_id],
                    set_={
                        "result": "NODE_ONLY",
                        "adapterId": None,
                        "adapterVersion": None,
                        "reasonCode": "COVERED_BY_OUTER_DIRECTORY_RESOURCE",
                    },
                    where=LibrarySourceNodeInterpretation.result != "NODE_ONLY",
                )
            )

    def insert_if_absent(
        self,
        *,
        library_id: str,
        parent_id: str | None,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]:
        existing = self.get_by_path_key(library_id, entry.relative_path.path_key)
        if existing is not None:
            collision = evaluate_path_key_occupancy(
                occupied_relative_path=SourceNodeRelativePath(existing.relative_path),
                candidate_relative_path=entry.relative_path,
            )
            if collision is not None:
                raise SourceNodeTopologyError(
                    collision.code,
                    relative_path=collision.relative_path,
                )
            return existing, False

        parent_tree: SourceNodeTreeNode | None = None
        if parent_id is not None:
            parent_record = self.get(parent_id)
            if parent_record is None:
                raise SourceNodeTopologyError(
                    SourceNodeViolationCode.PARENT_NOT_FOUND,
                    relative_path=entry.relative_path.value,
                )
            parent_tree = SourceNodeTreeNode(
                library_id=parent_record.library_id,
                relative_path=SourceNodeRelativePath(parent_record.relative_path),
                physical_kind=parent_record.physical_kind,
            )

        child = SourceNodeTreeNode(
            library_id=library_id,
            relative_path=entry.relative_path,
            physical_kind=entry.physical_kind,
        )
        violations = validate_source_node_direct_parent(node=child, parent=parent_tree)
        if violations:
            raise SourceNodeTopologyError(
                violations[0].code,
                relative_path=violations[0].relative_path,
            )

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

    def refresh_observation(
        self,
        *,
        source_node_id: str,
        entry: ObservedSourceEntry,
    ) -> tuple[SourceNodeRecord, bool]:
        row = self._session.get(LibrarySourceNode, source_node_id)
        if row is None:
            raise LookupError(source_node_id)
        if row.path_key != entry.relative_path.path_key:
            raise SourceNodeTopologyError(
                SourceNodeViolationCode.PATH_KEY_COLLISION,
                relative_path=entry.relative_path.value,
            )
        if row.physical_kind != entry.physical_kind.value:
            raise SourceNodeTopologyError(
                SourceNodeViolationCode.PHYSICAL_KIND_CHANGED,
                relative_path=entry.relative_path.value,
            )

        version_changed = (
            row.observed_size_bytes != entry.observed_size_bytes
            or row.observed_mtime_ns != entry.observed_mtime_ns
        )
        row.observed_size_bytes = entry.observed_size_bytes
        row.observed_mtime_ns = entry.observed_mtime_ns
        if version_changed:
            row.observed_at = entry.observed_at
        self._session.flush()
        return self._to_record(row), version_changed

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
        self.delete_nodes(ids)

    def delete_nodes(self, source_node_ids: Sequence[str]) -> None:
        if not source_node_ids:
            return
        self._session.execute(
            delete(LibrarySourceNode).where(
                LibrarySourceNode.id.in_(tuple(source_node_ids))
            )
        )
        self._session.flush()

    def get_interpretation(self, source_node_id: str) -> InterpretationRecord | None:
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
        if row is not None and (
            row.result,
            row.source,
            row.adapter_id,
            row.adapter_version,
            row.reason_code,
            row.sample_relative_paths,
            row.sample_count,
            row.max_entries_visited,
            row.max_depth,
            row.time_budget_ms,
            row.termination_reason,
        ) == (
            result,
            source,
            adapter_id,
            adapter_version,
            reason_code,
            sample_relative_paths,
            sample_count,
            max_entries_visited,
            max_depth,
            time_budget_ms,
            termination_reason,
        ):
            return
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
    def source_targets_for_books(
        self, book_ids: Sequence[str]
    ) -> tuple[ManagedBookSourceTarget, ...]:
        rows = self._session.execute(
            select(LibraryBook, LibrarySourceNode, Library)
            .join(LibrarySourceNode, LibrarySourceNode.id == LibraryBook.source_node_id)
            .join(Library, Library.id == LibraryBook.library_id)
            .where(LibraryBook.id.in_(book_ids))
        ).all()
        by_book_id = {
            book.id: ManagedBookSourceTarget(
                book_id=book.id,
                source_node_id=node.id,
                library_id=book.library_id,
                library_root=Path(library.root_path),
                relative_path=node.relative_path,
                physical_kind=SourceNodePhysicalKind(node.physical_kind),
            )
            for book, node, library in rows
        }
        return tuple(
            by_book_id[book_id] for book_id in book_ids if book_id in by_book_id
        )

    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_book(
        self,
        *,
        library_id: str,
        source_node_id: str,
        title: str,
    ) -> str:
        source_node = self._session.get(LibrarySourceNode, source_node_id)
        if source_node is None:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.SOURCE_NODE_NOT_FOUND,
                detail=source_node_id,
            )
        if source_node.library_id != library_id:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                detail=source_node_id,
            )
        existing = self._session.scalar(
            select(LibraryBook).where(LibraryBook.source_node_id == source_node_id)
        )
        if existing is not None:
            if existing.library_id != library_id:
                raise ReadableResourceTopologyError(
                    ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                    detail=existing.id,
                )
            return existing.id
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
    ) -> ReadableResourceRecord:
        existing = self.get_resource_by_source_node(source_node_id)
        if existing is not None:
            if existing.library_id != library_id or existing.book_id != book_id:
                raise ReadableResourceTopologyError(
                    ReadableResourceAnchorViolationCode.RESOURCE_ALREADY_ANCHORED,
                    detail=source_node_id,
                )
            return existing

        book = self._session.get(LibraryBook, book_id)
        if book is None:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.BOOK_NOT_FOUND,
                detail=book_id,
            )
        if book.library_id != library_id:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                detail=book_id,
            )
        book_anchor = self._session.get(LibrarySourceNode, book.source_node_id)
        resource_anchor = self._session.get(LibrarySourceNode, source_node_id)
        if book_anchor is None or resource_anchor is None:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.SOURCE_NODE_NOT_FOUND,
                detail=source_node_id
                if resource_anchor is None
                else book.source_node_id,
            )
        if (
            book_anchor.library_id != library_id
            or resource_anchor.library_id != library_id
        ):
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                detail=source_node_id,
            )
        if not is_resource_anchor_within_book_scope(
            book_anchor=SourceNodeRelativePath(book_anchor.relative_path),
            book_anchor_kind=SourceNodePhysicalKind(book_anchor.physical_kind),
            resource_anchor=SourceNodeRelativePath(resource_anchor.relative_path),
        ):
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.RESOURCE_OUT_OF_BOOK_SCOPE,
                detail=source_node_id,
            )

        row = LibraryReadableResource(
            id=cuid(),
            library_id=library_id,
            book_id=book_id,
            source_node_id=source_node_id,
            adapter_id=adapter.adapter_id,
            adapter_version=adapter.adapter_version,
            format=adapter.format_label,
            enablement_state=ResourceEnablementState.ENABLED.value,
            import_state=ResourceImportState.PENDING.value,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_resource(row)

    def refresh_resource_adapter(
        self,
        *,
        resource_id: str,
        adapter: AdapterIdentity,
    ) -> ReadableResourceRecord:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            raise LookupError(resource_id)
        row.adapter_id = adapter.adapter_id
        row.adapter_version = adapter.adapter_version
        row.format = adapter.format_label
        row.import_state = ResourceImportState.PENDING.value
        self._session.flush()
        return self._to_resource(row)

    def delete_resource(self, resource_id: str) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return
        self._session.delete(row)
        self._session.flush()

    def invalidate_asset_for_reimport(
        self,
        *,
        resource_id: str,
        source_node_id: str,
    ) -> bool:
        asset = self._session.scalar(
            select(LibraryResourceAsset).where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.source_node_id == source_node_id,
            )
        )
        if asset is None:
            return False

        SqlAlchemyLibraryNavigationProjection(self._session).invalidate_asset(
            resource_id=resource_id,
            asset_id=asset.id,
        )
        asset.import_state = AssetImportState.PENDING.value
        asset.failure_reason = None
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None:
            raise LookupError(resource_id)
        resource.import_state = (
            ResourceImportState.READY.value
            if self.count_ready_assets(resource_id) >= 1
            else ResourceImportState.PENDING.value
        )
        if asset.role == AssetRole.TRACK.value:
            self.refresh_audio_resource_aggregates(resource_id)
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

    def mark_resource_ready(
        self,
        *,
        resource_id: str,
        title: str | None = None,
    ) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            raise LookupError(resource_id)
        row.import_state = ResourceImportState.READY.value
        if title is not None:
            metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
            if metadata is None:
                self._session.add(
                    LibraryReadableResourceMetadata(
                        resource_id=resource_id, title=title
                    )
                )
            elif "title" not in protected_fields(metadata.protected_fields):
                metadata.title = title
        self._session.flush()

    def set_resource_page_count(self, resource_id: str, page_count: int | None) -> None:
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            raise LookupError(resource_id)
        metadata.page_count = max(0, page_count) if page_count is not None else None
        self._session.flush()

    def should_extract_first_page_cover(
        self, *, resource_id: str, source_node_id: str
    ) -> bool:
        resource = self._session.get(LibraryReadableResource, resource_id)
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if resource is None or (
            metadata is not None
            and "cover_path" in protected_fields(metadata.protected_fields)
        ):
            return False
        return resource.format == "PDF"

    def save_asset_local_metadata(
        self,
        *,
        resource_id: str,
        asset_id: str,
        observations: tuple[LocalMetadataObservation, ...],
        cover_path: str | None,
    ) -> None:
        """Save observations for this asset without resolving the resource."""
        asset = self._session.get(LibraryResourceAsset, asset_id)
        if asset is None or asset.resource_id != resource_id:
            raise LookupError(asset_id)
        asset.local_metadata_candidates = encode_observations(observations)
        asset.local_cover_path = cover_path
        self._session.flush()

    def refresh_resource_local_metadata(self, resource_id: str) -> None:
        """Resolve persisted ready-asset observations in canonical resource order."""
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None:
            raise LookupError(resource_id)
        assets = self._session.scalars(
            select(LibraryResourceAsset)
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )
            .order_by(
                LibraryResourceAsset.sequence_index.asc().nulls_last(),
                func.lower(LibraryResourceAsset.sort_key),
                LibraryResourceAsset.id,
            )
        ).all()
        if resource.format == "IMAGE_DIR":
            assets.sort(
                key=lambda item: (natural_sort_key(item.sort_key or ""), item.id)
            )
        grouped = merge_observations(
            tuple(
                candidate
                for item in assets
                for candidate in decode_observations(item.local_metadata_candidates)
            )
        )
        metadata = resolve_local_metadata(
            tuple(
                LocalMetadataCandidate(source=source, metadata=grouped[source])
                for source in SqlAlchemyLocalMetadataPriority(self._session).load()
                if source in grouped
            ),
            SqlAlchemyLocalMetadataPriority(self._session).load(),
        ).metadata
        cover_path = assets[0].local_cover_path if assets else None
        self.apply_local_metadata(
            resource_id=resource_id, metadata=metadata, cover_path=cover_path
        )

    def apply_local_metadata(
        self,
        *,
        resource_id: str,
        metadata: PublicationMetadata,
        cover_path: str | None = None,
    ) -> None:
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None:
            raise LookupError(resource_id)
        book = self._session.get(LibraryBook, resource.book_id)
        if book is None:
            raise LookupError(resource.book_id)
        book_metadata = self._session.get(LibraryBookMetadata, resource.book_id)
        if book_metadata is None:
            raise LookupError(resource.book_id)

        resource_metadata = self._session.get(
            LibraryReadableResourceMetadata, resource_id
        )
        resource_title = metadata.volume_title or metadata.title or book_metadata.title
        if resource_metadata is None:
            resource_metadata = LibraryReadableResourceMetadata(
                resource_id=resource_id,
                title=resource_title,
            )
            self._session.add(resource_metadata)
        protected = protected_fields(resource_metadata.protected_fields)
        if "title" not in protected:
            resource_metadata.title = resource_title
        if "description" not in protected:
            resource_metadata.description = metadata.description
        if "language" not in protected:
            resource_metadata.language = metadata.language
        if "publisher" not in protected:
            resource_metadata.publisher = metadata.publisher
        if "published_at" not in protected:
            resource_metadata.published_at = (
                _parse_publication_datetime(metadata.published_at)
                if metadata.published_at
                else None
            )
        if "identifier" not in protected:
            resource_metadata.identifier = metadata.identifier
        if "isbn" not in protected:
            resource_metadata.isbn = metadata.isbn
        if "narrator" not in protected:
            resource_metadata.narrator = " / ".join(metadata.narrators) or None
        if "abridged" not in protected:
            resource_metadata.abridged = metadata.abridged
        if "resource_index" not in protected:
            resource_metadata.resource_index = metadata.volume_index
        if "cover_path" not in protected:
            resource_metadata.cover_path = cover_path
            resource_metadata.cover_status = "READY" if cover_path else "PENDING"
        self._session.flush()

    def clear_local_cover(self, *, resource_id: str, expected_path: str) -> None:
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None:
            return
        resource_metadata = self._session.get(
            LibraryReadableResourceMetadata, resource_id
        )
        if (
            resource_metadata is not None
            and resource_metadata.cover_path == expected_path
        ):
            resource_metadata.cover_path = None
            resource_metadata.cover_status = "FAILED"
        self._session.flush()

    def mark_resource_failed(self, resource_id: str) -> None:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            return
        row.import_state = ResourceImportState.FAILED.value
        self._session.flush()

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
        metadata: ResourceAssetMetadataInput | None = None,
        processed_source_version: str | None = None,
    ) -> str:
        # Keep the existing port field for compatibility, but persist the canonical
        # SourceNode path computed below instead of adapter-provided ordering hints.
        del sort_key
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.RESOURCE_NOT_FOUND,
                detail=resource_id,
            )
        if resource.library_id != library_id:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                detail=resource_id,
            )
        asset_node = self._session.get(LibrarySourceNode, source_node_id)
        resource_anchor = self._session.get(LibrarySourceNode, resource.source_node_id)
        if asset_node is None or resource_anchor is None:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.SOURCE_NODE_NOT_FOUND,
                detail=source_node_id
                if asset_node is None
                else resource.source_node_id,
            )
        if asset_node.library_id != library_id:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.CROSS_LIBRARY,
                detail=source_node_id,
            )
        if asset_node.physical_kind != SourceNodePhysicalKind.REGULAR_FILE.value:
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.ASSET_SOURCE_NOT_REGULAR_FILE,
                detail=source_node_id,
            )
        if not is_asset_path_within_resource_scope(
            resource_anchor=SourceNodeRelativePath(resource_anchor.relative_path),
            resource_anchor_kind=SourceNodePhysicalKind(resource_anchor.physical_kind),
            asset_path=SourceNodeRelativePath(asset_node.relative_path),
            adapter_id=resource.adapter_id,
        ):
            raise ReadableResourceTopologyError(
                ReadableResourceAnchorViolationCode.ASSET_OUT_OF_RESOURCE_SCOPE,
                detail=source_node_id,
            )

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
        row.role = role.value
        row.import_state = import_state.value
        row.sequence_index = sequence_index
        row.sort_key = resource_relative_asset_sort_key(
            resource_anchor=SourceNodeRelativePath(resource_anchor.relative_path),
            asset_path=SourceNodeRelativePath(asset_node.relative_path),
        )
        if (
            import_state is AssetImportState.READY
            and processed_source_version is not None
        ):
            row.processed_source_version = processed_source_version
        row.failure_reason = failure_reason
        self._session.flush()
        if metadata is not None:
            metadata_row = self._session.get(LibraryResourceAssetMetadata, row.id)
            if metadata_row is None:
                metadata_row = LibraryResourceAssetMetadata(asset_id=row.id)
                self._session.add(metadata_row)
            metadata_row.title = metadata.title
            metadata_row.mime_type = metadata.mime_type
            metadata_row.duration_ms = metadata.duration_ms
            metadata_row.codec = metadata.codec
            metadata_row.bitrate = metadata.bitrate
            metadata_row.sample_rate = metadata.sample_rate
            metadata_row.channels = metadata.channels
            metadata_row.disc_number = metadata.disc_number
            metadata_row.track_number = metadata.track_number
            self._session.flush()
        return row.id

    def refresh_scan_context(self, resource_id: str, version: str) -> bool:
        row = self._session.get(LibraryReadableResource, resource_id)
        if row is None:
            raise LookupError(resource_id)
        if row.scan_context_version == version:
            return False
        row.scan_context_version = version
        self._session.flush()
        return True

    def load_directory_members(
        self, resource_id: str
    ) -> tuple[DirectoryImportMember, ...]:
        resource = self._session.get(LibraryReadableResource, resource_id)
        if resource is None or resource.format not in {"IMAGE_DIR", "AUDIOBOOK_DIR"}:
            raise LookupError(resource_id)
        anchor = self._session.get(LibrarySourceNode, resource.source_node_id)
        if anchor is None:
            raise LookupError(resource.source_node_id)
        rows = self._session.execute(
            select(
                LibrarySourceNode,
                LibraryResourceAsset.processed_source_version,
                LibraryResourceAsset.import_state,
            )
            .outerjoin(
                LibraryResourceAsset,
                (LibraryResourceAsset.source_node_id == LibrarySourceNode.id)
                & (LibraryResourceAsset.resource_id == resource_id),
            )
            .where(
                LibrarySourceNode.library_id == resource.library_id,
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
                LibrarySourceNode.relative_path.startswith(
                    anchor.relative_path + "/", autoescape=True
                ),
            )
        ).all()
        return tuple(
            DirectoryImportMember(
                node=SourceNodeRecord(
                    id=n.id,
                    library_id=n.library_id,
                    parent_id=n.parent_id,
                    relative_path=n.relative_path,
                    path_key=n.path_key,
                    name=n.name,
                    physical_kind=SourceNodePhysicalKind(n.physical_kind),
                    observed_size_bytes=n.observed_size_bytes,
                    observed_mtime_ns=n.observed_mtime_ns,
                    observed_at=n.observed_at,
                ),
                processed_version=version,
                ready=state == "READY",
            )
            for n, version, state in rows
            if is_asset_path_within_resource_scope(
                resource_anchor=SourceNodeRelativePath(anchor.relative_path),
                resource_anchor_kind=SourceNodePhysicalKind(anchor.physical_kind),
                asset_path=SourceNodeRelativePath(n.relative_path),
                adapter_id=resource.adapter_id,
            )
        )

    def single_file_fallback_cover(self, resource_id: str) -> str | None:
        asset = self._session.scalar(
            select(LibraryResourceAsset)
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )
            .limit(1)
        )
        if asset is None or asset.local_cover_path is None:
            return None
        candidate_paths = {
            o.cover_path for o in decode_observations(asset.local_metadata_candidates)
        }
        return (
            asset.local_cover_path
            if asset.local_cover_path not in candidate_paths
            else None
        )

    def resource_cover_state(self, resource_id: str) -> ResourceCoverState:
        row = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if row is None:
            return ResourceCoverState(None, False)
        return ResourceCoverState(
            row.cover_path, "cover_path" in protected_fields(row.protected_fields)
        )

    def save_directory_assets(
        self,
        *,
        library_id: str,
        resource_id: str,
        results: tuple[DirectoryAssetResult, ...],
    ) -> None:
        if not results or len(results) > 200:
            raise ValueError("INVALID_DIRECTORY_BATCH_SIZE")
        resource = self._session.get(LibraryReadableResource, resource_id)
        if (
            resource is None
            or resource.library_id != library_id
            or resource.format not in {"IMAGE_DIR", "AUDIOBOOK_DIR"}
        ):
            raise ValueError("INVALID_DIRECTORY_RESOURCE")
        anchor = self._session.get(LibrarySourceNode, resource.source_node_id)
        if anchor is None:
            raise ValueError("MISSING_RESOURCE_ANCHOR")
        nodes = {
            n.id: n
            for n in self._session.scalars(
                select(LibrarySourceNode)
                .where(LibrarySourceNode.id.in_([r.node.id for r in results]))
                .execution_options(populate_existing=True)
            )
        }
        assets = []
        for result in results:
            node = nodes.get(result.node.id)
            if (
                node is None
                or node.library_id != library_id
                or node.physical_kind != "REGULAR_FILE"
                or Path(node.name).suffix.lower()
                not in (
                    READER_SAFETY_COMIC_PROFILE.page_mime_types_by_extension
                    if resource.format == "IMAGE_DIR"
                    else READER_SAFETY_AUDIO_PROFILE.container_mime_types
                )
                or not is_asset_path_within_resource_scope(
                    resource_anchor=SourceNodeRelativePath(anchor.relative_path),
                    resource_anchor_kind=SourceNodePhysicalKind(anchor.physical_kind),
                    asset_path=SourceNodeRelativePath(node.relative_path),
                    adapter_id=resource.adapter_id,
                )
            ):
                raise ValueError("INVALID_DIRECTORY_ASSET_TARGET")
            if (
                node.observed_size_bytes != result.node.observed_size_bytes
                or node.observed_mtime_ns != result.node.observed_mtime_ns
            ):
                raise ValueError("DIRECTORY_INPUT_CHANGED")
            assets.append(
                {
                    "id": cuid(),
                    "library_id": library_id,
                    "resource_id": resource_id,
                    "source_node_id": node.id,
                    "source_node_physical_kind": "REGULAR_FILE",
                    "role": "PAGE" if resource.format == "IMAGE_DIR" else "TRACK",
                    "import_state": "READY" if result.error is None else "FAILED",
                    "sort_key": resource_relative_asset_sort_key(
                        resource_anchor=SourceNodeRelativePath(anchor.relative_path),
                        asset_path=SourceNodeRelativePath(node.relative_path),
                    ),
                    "failure_reason": result.error,
                    "processed_source_version": result.processed_version,
                    "local_metadata_candidates": encode_observations(
                        result.observations
                    ),
                    "local_cover_path": None,
                }
            )
        table = LibraryResourceAsset.__table__
        # Bound statement parameters independently of the 200-file business commit.
        for offset in range(0, len(assets), 50):
            statement = sqlite_insert(LibraryResourceAsset).values(
                assets[offset : offset + 50]
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[table.c.resourceId, table.c.sourceNodeId],
                    set_={
                        name: getattr(statement.excluded, name)
                        for name in (
                            "role",
                            "importState",
                            "sortKey",
                            "failureReason",
                            "localMetadataCandidates",
                            "localCoverPath",
                            "updatedAt",
                        )
                    }
                    | {
                        "processedSourceVersion": func.coalesce(
                            statement.excluded.processedSourceVersion,
                            table.c.processedSourceVersion,
                        )
                    },
                )
            )
        ids = dict(
            self._session.execute(
                select(
                    LibraryResourceAsset.source_node_id, LibraryResourceAsset.id
                ).where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.source_node_id.in_(list(nodes)),
                )
            ).all()
        )
        metadata = [
            {
                "asset_id": ids[r.node.id],
                **(
                    asdict(
                        r.metadata
                        or ResourceAssetMetadataInput(
                            title=r.title, mime_type=r.mime_type
                        )
                    )
                    if resource.format == "AUDIOBOOK_DIR"
                    else {"title": r.title, "mime_type": r.mime_type}
                ),
            }
            for r in results
            if r.error is None
        ]
        metadata_batch_size = 40 if resource.format == "AUDIOBOOK_DIR" else 100
        for offset in range(0, len(metadata), metadata_batch_size):
            statement = sqlite_insert(LibraryResourceAssetMetadata).values(
                metadata[offset : offset + metadata_batch_size]
            )
            self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[LibraryResourceAssetMetadata.asset_id],
                    set_={
                        "title": statement.excluded.title,
                        "mimeType": statement.excluded.mimeType,
                        "updatedAt": statement.excluded.updatedAt,
                        **(
                            {
                                key: getattr(statement.excluded, key)
                                for key in (
                                    "durationMs",
                                    "codec",
                                    "bitrate",
                                    "sampleRate",
                                    "channels",
                                    "discNumber",
                                    "trackNumber",
                                )
                            }
                            if resource.format == "AUDIOBOOK_DIR"
                            else {}
                        ),
                    },
                )
            )

        if resource.format == "AUDIOBOOK_DIR":
            # Replace only files in this batch; existing chapter IDs on other
            # tracks survive. Allocate disjoint temporary slots before final ordering.
            self._session.execute(
                delete(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource_id,
                    ReadableResourceNavigationUnit.asset_id.in_(list(ids.values())),
                )
            )
            maximum = self._session.scalar(
                select(func.max(ReadableResourceNavigationUnit.sort_order)).where(
                    ReadableResourceNavigationUnit.resource_id == resource_id
                )
            )
            next_order = 0 if maximum is None else maximum + 1
            chapters = []
            for result in results:
                if result.error is not None:
                    continue
                for unit in result.units:
                    chapters.append(
                        {
                            "id": cuid(),
                            "resource_id": resource_id,
                            "asset_id": ids[result.node.id],
                            "unit_type": unit.unit_type,
                            "title": unit.title,
                            "href": unit.href,
                            "media_type": unit.media_type,
                            "sort_order": next_order,
                            "start_ms": unit.start_ms,
                            "end_ms": unit.end_ms,
                            "duration_ms": unit.duration_ms,
                            "metadata_json": "{}",
                        }
                    )
                    next_order += 1
            for offset in range(0, len(chapters), 50):
                self._session.execute(
                    sqlite_insert(ReadableResourceNavigationUnit).values(
                        chapters[offset : offset + 50]
                    )
                )

    def resource_local_observations(
        self, resource_id: str
    ) -> tuple[LocalMetadataObservation, ...]:
        rows = self._session.execute(
            select(LibraryResourceAsset, LibraryResourceAssetMetadata)
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
            )
        ).all()
        ordered = sorted(
            rows,
            key=lambda row: (
                row[1].disc_number if row[1] and row[1].disc_number else 1,
                row[1].track_number
                if row[1] and row[1].track_number is not None
                else 10**9,
                natural_sort_key(row[0].sort_key or ""),
                row[0].id,
            ),
        )
        return tuple(
            candidate
            for asset, _ in ordered
            for candidate in decode_observations(asset.local_metadata_candidates)
        )

    def asset_has_processed_version(
        self,
        *,
        resource_id: str,
        source_node_id: str,
        version: str,
    ) -> bool:
        return (
            self._session.scalar(
                select(LibraryResourceAsset.id).where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.source_node_id == source_node_id,
                    LibraryResourceAsset.import_state == "READY",
                    LibraryResourceAsset.processed_source_version == version,
                )
            )
            is not None
        )

    def count_ready_assets(self, resource_id: str) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(LibraryResourceAsset)
                .where(
                    LibraryResourceAsset.resource_id == resource_id,
                    LibraryResourceAsset.import_state == AssetImportState.READY.value,
                )
            )
            or 0
        )

    def refresh_audio_resource_aggregates(self, resource_id: str) -> None:
        rows = self._session.execute(
            select(
                LibraryResourceAsset,
                LibraryResourceAssetMetadata,
                LibrarySourceNode,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == AssetImportState.READY.value,
                LibraryResourceAsset.role == AssetRole.TRACK.value,
            )
        ).all()
        ordered_rows = sorted(
            rows,
            key=lambda item: (
                item[1].disc_number if item[1] and item[1].disc_number else 1,
                item[1].track_number
                if item[1] and item[1].track_number is not None
                else 10**9,
                natural_sort_key(item[2].relative_path),
                item[0].id,
            ),
        )
        asset_order: dict[str, int] = {}
        for index, (asset, _asset_metadata, _source) in enumerate(ordered_rows):
            asset.sequence_index = index
            asset_order[asset.id] = index

        asset_ids = tuple(asset_order)
        units = (
            self._session.scalars(
                select(ReadableResourceNavigationUnit).where(
                    ReadableResourceNavigationUnit.resource_id == resource_id,
                    ReadableResourceNavigationUnit.asset_id.in_(asset_ids),
                )
            ).all()
            if asset_ids
            else []
        )
        ordered_units = sorted(
            units,
            key=lambda unit: (
                asset_order.get(unit.asset_id or "", 10**9),
                unit.start_ms if unit.start_ms is not None else unit.sort_order,
                unit.id,
            ),
        )
        # Removed tracks can leave gaps, so the remaining count is not a safe
        # offset. Move every unit beyond the current maximum before compacting.
        temporary_start = max((unit.sort_order for unit in units), default=-1) + 1
        for index, unit in enumerate(ordered_units):
            unit.sort_order = temporary_start + index
        self._session.flush()
        for index, unit in enumerate(ordered_units):
            unit.sort_order = index

        resource_metadata = self._session.get(
            LibraryReadableResourceMetadata, resource_id
        )
        if resource_metadata is None:
            raise LookupError(resource_id)
        resource_metadata.track_count = len(ordered_rows)
        durations = [
            asset_metadata.duration_ms if asset_metadata is not None else None
            for _asset, asset_metadata, _source in ordered_rows
        ]
        resource_metadata.duration_ms = (
            sum(value for value in durations if value is not None)
            if durations and all(value is not None for value in durations)
            else None
        )
        resource_metadata.chapter_count = len(ordered_units)
        self._session.flush()

    def replace_navigation_units(
        self,
        *,
        resource_id: str,
        asset_id: str,
        units: Sequence[ResourceNavigationUnitInput],
    ) -> None:
        self._session.execute(
            delete(ReadableResourceNavigationUnit).where(
                ReadableResourceNavigationUnit.resource_id == resource_id,
                ReadableResourceNavigationUnit.asset_id == asset_id,
            )
        )
        if not units:
            return
        current_max = self._session.scalar(
            select(func.max(ReadableResourceNavigationUnit.sort_order)).where(
                ReadableResourceNavigationUnit.resource_id == resource_id
            )
        )
        base_sort_order = 0 if current_max is None else int(current_max) + 1
        self._session.add_all(
            [
                ReadableResourceNavigationUnit(
                    id=cuid(),
                    resource_id=resource_id,
                    asset_id=asset_id,
                    unit_type=unit.unit_type,
                    title=unit.title,
                    href=unit.href,
                    media_type=unit.media_type,
                    sort_order=base_sort_order + unit.sort_order,
                    width=unit.width,
                    height=unit.height,
                    size=unit.size,
                    start_ms=unit.start_ms,
                    end_ms=unit.end_ms,
                    duration_ms=unit.duration_ms,
                    metadata_json="{}",
                )
                for unit in units
            ]
        )
        self._session.flush()

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
        path_keys = [SourceNodeRelativePath(path).path_key for path in candidates]
        nodes = self._session.scalars(
            select(LibrarySourceNode).where(
                LibrarySourceNode.library_id == library_id,
                LibrarySourceNode.path_key.in_(path_keys),
                LibrarySourceNode.physical_kind == "DIRECTORY",
            )
        ).all()
        by_path = {node.relative_path: node for node in nodes}
        candidate_node = self._session.scalar(
            select(LibrarySourceNode).where(
                LibrarySourceNode.library_id == library_id,
                LibrarySourceNode.path_key
                == SourceNodeRelativePath(relative_path).path_key,
            )
        )
        for path in candidates:
            node = by_path.get(path)
            if node is None:
                continue
            resource = self.get_resource_by_source_node(node.id)
            if resource is None:
                continue
            if (
                resource.adapter_id == "audiobook-directory"
                and candidate_node is not None
                and not audiobook_resource_owns_path(
                    resource_anchor=SourceNodeRelativePath(node.relative_path),
                    candidate_path=SourceNodeRelativePath(relative_path),
                    candidate_kind=SourceNodePhysicalKind(candidate_node.physical_kind),
                )
            ):
                continue
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
        navigation = SqlAlchemyLibraryNavigationProjection(self._session)
        for row in rows:
            navigation.invalidate_asset(
                resource_id=row.resource_id,
                asset_id=row.id,
            )
        self._session.execute(
            delete(LibraryResourceAsset).where(
                LibraryResourceAsset.source_node_id.in_(tuple(source_node_ids))
            )
        )
        self._session.flush()
        return resource_ids

    def reevaluate_ready_after_asset_loss(self, resource_ids: Sequence[str]) -> None:
        for resource_id in resource_ids:
            resource = self.get_resource(resource_id)
            if resource is None:
                continue
            if self.count_ready_assets(resource_id) < 1:
                self.mark_resource_failed(resource_id)

    def _to_resource(self, row: LibraryReadableResource) -> ReadableResourceRecord:
        return ReadableResourceRecord(
            id=row.id,
            library_id=row.library_id,
            book_id=row.book_id,
            source_node_id=row.source_node_id,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            format=row.format,
            enablement_state=ResourceEnablementState(row.enablement_state),
            import_state=ResourceImportState(row.import_state),
        )


def _parse_publication_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        record_exception(logging.getLogger(__name__), "modules.library.infrastructure.persistence.source_tree_repository._parse_publication_datetime.failed", error,
                         context={"step": "_parse_publication_datetime"})
        return None
