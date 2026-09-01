"""ORM and filesystem adapters for local metadata cover regeneration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.infrastructure.local_metadata_policy import SqlAlchemyLocalMetadataPriority
from app.models import (
    Library,
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.modules.library.application.bulk_operations import (
    BulkCoverCommand,
    BulkCoverSkipped,
)
from app.modules.library.application.local_cover_regeneration import (
    BulkCoverRegenerationOperationPort,
    LocalCoverExtraction,
    LocalCoverFailureCode,
    LocalCoverRegenerationResult,
    LocalCoverScope,
    LocalCoverSourcePort,
    ResourceLocalMetadataSource,
)
from app.modules.library.application.resource_commands import OperationSummary
from app.modules.library.infrastructure import operations as operation_store
from app.modules.metadata.public import FilesystemLocalMetadataInspector


class FilesystemLocalMetadataCoverParser:
    """Read only the cover field through the canonical metadata inspector."""

    def __init__(self, inspector: FilesystemLocalMetadataInspector) -> None:
        self._inspector = inspector

    def extract_cover(
        self, source: ResourceLocalMetadataSource
    ) -> LocalCoverExtraction:
        try:
            root = source.root_path.expanduser().resolve(strict=True)
            resource_path = (root / source.resource_relative_path).resolve(strict=True)
            resource_path.relative_to(root)
        except (OSError, ValueError):
            return LocalCoverExtraction(
                content=None,
                failure_code="LOCAL_METADATA_SOURCE_UNAVAILABLE",
            )

        saw_readable_source = False
        saw_parse_failure = False
        source_format = self._metadata_source_format(source)
        for relative_path in source.asset_relative_paths:
            try:
                asset_path = (root / relative_path).resolve(strict=True)
                asset_path.relative_to(root)
                if not asset_path.is_file():
                    continue
                saw_readable_source = True
                resolved = self._inspector.inspect(
                    asset_path,
                    resource_path=resource_path,
                    source_format=source_format,
                    source_order=source.local_metadata_priority,
                )
            except OSError:
                continue
            except (RuntimeError, ValueError):
                saw_parse_failure = True
                continue
            if resolved.cover is not None:
                return LocalCoverExtraction(content=resolved.cover.content)

        failure: LocalCoverFailureCode
        if not saw_readable_source:
            failure = "LOCAL_METADATA_SOURCE_UNAVAILABLE"
        elif saw_parse_failure:
            failure = "LOCAL_METADATA_PARSE_FAILED"
        else:
            failure = "LOCAL_COVER_NOT_FOUND"
        return LocalCoverExtraction(content=None, failure_code=failure)

    @staticmethod
    def _metadata_source_format(source: ResourceLocalMetadataSource) -> str:
        if source.adapter_id == "audio-file":
            return "AUDIO"
        if source.adapter_id == "audiobook-directory":
            return "AUDIOBOOK_DIRECTORY"
        return source.source_format


class SqlAlchemyLocalCoverSources(LocalCoverSourcePort):
    """Resolve existing Resource/Asset topology without discovering new files."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._priority = SqlAlchemyLocalMetadataPriority(db)

    def load_resource_source(
        self, *, book_id: str, resource_id: str
    ) -> ResourceLocalMetadataSource | None:
        resource_node = aliased(LibrarySourceNode)
        row = self._db.execute(
            select(LibraryReadableResource, Library, resource_node)
            .join(Library, Library.id == LibraryReadableResource.library_id)
            .join(
                resource_node,
                resource_node.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
            )
        ).one_or_none()
        if row is None:
            return None
        resource, library, anchor = row
        asset_node = aliased(LibrarySourceNode)
        asset_rows = self._db.execute(
            select(
                LibraryResourceAsset.id,
                LibraryResourceAsset.sequence_index,
                LibraryResourceAsset.sort_key,
                asset_node.relative_path,
            )
            .join(asset_node, asset_node.id == LibraryResourceAsset.source_node_id)
            .where(LibraryResourceAsset.resource_id == resource.id)
            .order_by(
                func.coalesce(LibraryResourceAsset.sequence_index, 2_147_483_647),
                func.lower(
                    func.coalesce(
                        LibraryResourceAsset.sort_key,
                        asset_node.relative_path,
                    )
                ),
                func.lower(asset_node.relative_path),
                LibraryResourceAsset.id,
            )
        ).all()
        asset_paths = tuple(
            dict.fromkeys(str(asset.relative_path) for asset in asset_rows)
        )
        if not asset_paths and anchor.physical_kind == "REGULAR_FILE":
            asset_paths = (str(anchor.relative_path),)
        return ResourceLocalMetadataSource(
            resource_id=str(resource.id),
            book_id=str(resource.book_id),
            source_node_id=str(resource.source_node_id),
            adapter_id=str(resource.adapter_id),
            source_format=str(resource.format),
            root_path=Path(str(library.root_path)),
            resource_relative_path=str(anchor.relative_path),
            asset_relative_paths=asset_paths,
            local_metadata_priority=self._priority.load(),
        )

    def source_scope(
        self, *, book_id: str, source_node_id: str
    ) -> LocalCoverScope | None:
        context = self._book_node_context(
            book_id=book_id,
            source_node_id=source_node_id,
        )
        if context is None:
            return None
        book, root, node = context
        if node.id != root.id and node.physical_kind != "DIRECTORY":
            return None
        return LocalCoverScope(
            book_id=str(book.id),
            source_node_id=str(node.id),
            resource_ids=self._resource_ids_under(
                book_id=str(book.id),
                node=node,
            ),
            is_book_root=node.id == root.id,
        )

    def book_scope(self, *, book_id: str) -> LocalCoverScope | None:
        row = self._db.execute(
            select(LibraryBook, LibrarySourceNode)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryBook.source_node_id,
            )
            .where(LibraryBook.id == book_id)
        ).one_or_none()
        if row is None:
            return None
        book, root = row
        return LocalCoverScope(
            book_id=str(book.id),
            source_node_id=str(root.id),
            resource_ids=self._resource_ids_under(
                book_id=str(book.id),
                node=root,
            ),
            is_book_root=True,
        )

    def current_resource_cover_path(self, resource_id: str) -> str | None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        return metadata.cover_path if metadata is not None else None

    def current_source_cover_path(self, source_node_id: str) -> str | None:
        metadata = self._db.get(LibrarySourceNodeMetadata, source_node_id)
        return metadata.cover_path if metadata is not None else None

    def mark_resource_cover_ready(
        self, *, resource_id: str, cover_path: str
    ) -> None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            raise LookupError(resource_id)
        metadata.cover_path = cover_path
        metadata.cover_status = "READY"
        self._db.flush()

    def mark_source_cover_ready(
        self,
        *,
        scope: LocalCoverScope,
        cover_path: str,
    ) -> None:
        metadata = self._db.get(LibrarySourceNodeMetadata, scope.source_node_id)
        if metadata is None:
            metadata = LibrarySourceNodeMetadata(source_node_id=scope.source_node_id)
            self._db.add(metadata)
        metadata.cover_path = cover_path
        metadata.cover_status = "READY"
        if scope.is_book_root:
            book_metadata = self._db.get(LibraryBookMetadata, scope.book_id)
            if book_metadata is None:
                raise LookupError(scope.book_id)
            book_metadata.cover_path = cover_path
            book_metadata.cover_status = "READY"
        self._db.flush()

    def _book_node_context(
        self, *, book_id: str, source_node_id: str
    ) -> tuple[LibraryBook, LibrarySourceNode, LibrarySourceNode] | None:
        root = aliased(LibrarySourceNode)
        node = aliased(LibrarySourceNode)
        row = self._db.execute(
            select(LibraryBook, root, node)
            .join(root, root.id == LibraryBook.source_node_id)
            .join(node, node.id == source_node_id)
            .where(
                LibraryBook.id == book_id,
                node.library_id == LibraryBook.library_id,
            )
        ).one_or_none()
        if row is None:
            return None
        book, root_row, node_row = row
        root_path = str(root_row.relative_path).rstrip("/")
        node_path = str(node_row.relative_path)
        inside = (
            node_row.id == root_row.id
            or not root_path
            or node_path.startswith(f"{root_path}/")
        )
        return (book, root_row, node_row) if inside else None

    def _resource_ids_under(
        self, *, book_id: str, node: LibrarySourceNode
    ) -> tuple[str, ...]:
        resource_node = aliased(LibrarySourceNode)
        prefix = str(node.relative_path).rstrip("/")
        descendants = (
            resource_node.id == node.id
            if not prefix
            else (
                (resource_node.id == node.id)
                | resource_node.relative_path.startswith(
                    f"{prefix}/",
                    autoescape=True,
                )
            )
        )
        return tuple(
            str(resource_id)
            for resource_id in self._db.scalars(
                select(LibraryReadableResource.id)
                .join(
                    resource_node,
                    resource_node.id == LibraryReadableResource.source_node_id,
                )
                .where(
                    LibraryReadableResource.book_id == book_id,
                    LibraryReadableResource.enablement_state == "ENABLED",
                    descendants,
                )
                .order_by(
                    func.lower(resource_node.relative_path),
                    LibraryReadableResource.id,
                )
            )
        )


class SqlAlchemyBulkCoverRegenerationOperations(
    BulkCoverRegenerationOperationPort
):
    def __init__(self, db: Session) -> None:
        self._db = db

    def record(
        self,
        *,
        command: BulkCoverCommand,
        updated_book_ids: tuple[str, ...],
        skipped: tuple[BulkCoverSkipped, ...],
        results: tuple[LocalCoverRegenerationResult, ...],
    ) -> OperationSummary:
        operation = operation_store.create_operation(
            self._db,
            user_id=command.context.user_id,
            action="BULK_BOOK_COVERS",
            target_type="books",
            target_id=None,
            summary=f"重新解析 {len(updated_book_ids)} 本图书的本地封面",
            payload={
                "bookIds": list(command.book_ids),
                "action": "regenerate",
                "updatedBookIds": list(updated_book_ids),
                "results": [
                    {
                        "bookId": result.target_id,
                        "updatedResourceIds": list(result.updated_resource_ids),
                        "skippedResources": [
                            {
                                "resourceId": item.resource_id,
                                "reason": item.reason,
                            }
                            for item in result.skipped
                        ],
                    }
                    for result in results
                ],
                "skipped": [
                    {"bookId": item.book_id, "reason": item.reason}
                    for item in skipped
                ],
            },
            inverse={},
            now=datetime.now(UTC),
            undoable=False,
        )
        return operation_store.operation_summary(operation)


__all__ = [
    "FilesystemLocalMetadataCoverParser",
    "SqlAlchemyBulkCoverRegenerationOperations",
    "SqlAlchemyLocalCoverSources",
]
