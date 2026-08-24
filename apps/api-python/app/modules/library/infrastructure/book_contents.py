"""SQLAlchemy queries for the Book SourceNode content browser."""

from __future__ import annotations

from sqlalchemy import case, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    LibraryBook,
    LibraryReadableResource,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.modules.library.application.book_contents import (
    BookContentNode,
    BookContentSort,
    SortDirection,
)


class SqlAlchemyBookContentsQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_book_root(self, book_id: str) -> BookContentNode | None:
        row = self._db.execute(
            select(LibrarySourceNode, LibrarySourceNodeMetadata)
            .join(
                LibraryBook,
                (LibraryBook.source_node_id == LibrarySourceNode.id)
                & (LibraryBook.library_id == LibrarySourceNode.library_id),
            )
            .outerjoin(
                LibrarySourceNodeMetadata,
                LibrarySourceNodeMetadata.source_node_id == LibrarySourceNode.id,
            )
            .where(LibraryBook.id == book_id)
        ).one_or_none()
        if row is None:
            return None
        node, metadata = row
        resource_id = self._resource_id(book_id, node.id)
        return self._node(
            node,
            metadata=metadata,
            resource_id=resource_id,
            representative_resource_id=next(
                iter(
                    self.list_resource_ids_under(
                        book_id=book_id,
                        source_node_id=node.id,
                    )
                ),
                None,
            ),
        )

    def get_node(self, source_node_id: str) -> BookContentNode | None:
        row = self._db.execute(
            select(LibrarySourceNode, LibrarySourceNodeMetadata)
            .outerjoin(
                LibrarySourceNodeMetadata,
                LibrarySourceNodeMetadata.source_node_id == LibrarySourceNode.id,
            )
            .where(LibrarySourceNode.id == source_node_id)
        ).one_or_none()
        if row is None:
            return None
        node, metadata = row
        resource_id = self._resource_id_for_node(node.id)
        return self._node(
            node,
            metadata=metadata,
            resource_id=resource_id,
            representative_resource_id=resource_id,
        )

    def list_resource_ids_under(
        self, *, book_id: str, source_node_id: str
    ) -> tuple[str, ...]:
        node = self._db.get(LibrarySourceNode, source_node_id)
        if node is None:
            return ()
        prefix = f"{node.relative_path.rstrip('/')}"
        statement = (
            select(LibraryReadableResource.id)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                (LibrarySourceNode.id == source_node_id)
                | LibrarySourceNode.relative_path.startswith(
                    f"{prefix}/", autoescape=True
                ),
            )
            .order_by(
                func.lower(LibrarySourceNode.relative_path).asc(),
                LibraryReadableResource.id.asc(),
            )
        )
        return tuple(str(resource_id) for resource_id in self._db.scalars(statement))

    def list_children(
        self,
        *,
        book_id: str,
        parent_source_node_id: str,
        sort: BookContentSort,
        direction: SortDirection,
        limit: int,
        offset: int,
    ) -> tuple[tuple[BookContentNode, ...], int]:
        readable_resource = exists(
            select(LibraryReadableResource.id).where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.source_node_id == LibrarySourceNode.id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
            )
        )
        visible_content = (
            LibrarySourceNode.physical_kind == "DIRECTORY"
        ) | readable_resource
        direction_method = "asc" if direction == "asc" else "desc"
        folder_order = case(
            (LibrarySourceNode.physical_kind == "DIRECTORY", 0), else_=1
        )
        selected_order = {
            "name": func.lower(LibrarySourceNode.name),
            "type": LibrarySourceNode.physical_kind,
            "updated": LibrarySourceNode.observed_at,
            "size": func.coalesce(LibrarySourceNode.observed_size_bytes, 0),
        }[sort]
        statement = (
            select(
                LibrarySourceNode,
                LibrarySourceNodeMetadata,
            )
            .outerjoin(
                LibrarySourceNodeMetadata,
                LibrarySourceNodeMetadata.source_node_id == LibrarySourceNode.id,
            )
            .where(
                LibrarySourceNode.parent_id == parent_source_node_id,
                visible_content,
            )
            .order_by(
                folder_order.asc(),
                getattr(selected_order, direction_method)(),
                func.lower(LibrarySourceNode.name).asc(),
                LibrarySourceNode.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        rows = self._db.execute(statement).all()
        total = int(
            self._db.scalar(
                select(func.count(LibrarySourceNode.id)).where(
                    LibrarySourceNode.parent_id == parent_source_node_id,
                    visible_content,
                )
            )
            or 0
        )
        nodes = [row[0] for row in rows]
        resource_ids = self._resource_ids(book_id, [node.id for node in nodes])
        resource_nodes = aliased(LibrarySourceNode)
        resource_rows = self._db.execute(
            select(
                LibraryReadableResource.id,
                resource_nodes.relative_path,
            )
            .join(
                resource_nodes,
                resource_nodes.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
            )
            .order_by(
                func.lower(resource_nodes.relative_path).asc(),
                LibraryReadableResource.id.asc(),
            )
        ).all()
        representative_ids = {
            node.id: next(
                (
                    str(resource_id)
                    for resource_id, relative_path in resource_rows
                    if relative_path == node.relative_path
                    or relative_path.startswith(f"{node.relative_path.rstrip('/')}/")
                ),
                None,
            )
            for node in nodes
        }
        has_nested_resources = {
            node.id: any(
                relative_path.startswith(f"{node.relative_path.rstrip('/')}/")
                for _resource_id, relative_path in resource_rows
            )
            for node in nodes
        }
        return (
            tuple(
                self._node(
                    node,
                    metadata=row[1],
                    has_children=has_nested_resources[node.id],
                    resource_id=resource_ids.get(node.id),
                    representative_resource_id=representative_ids.get(node.id),
                )
                for node, row in zip(nodes, rows, strict=True)
            ),
            total,
        )

    def _resource_id(self, book_id: str, source_node_id: str) -> str | None:
        return self._resource_ids(book_id, [source_node_id]).get(source_node_id)

    def _resource_id_for_node(self, source_node_id: str) -> str | None:
        return self._db.scalar(
            select(LibraryReadableResource.id).where(
                LibraryReadableResource.source_node_id == source_node_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
            )
        )

    def _resource_ids(self, book_id: str, source_node_ids: list[str]) -> dict[str, str]:
        if not source_node_ids:
            return {}
        anchored = {
            str(source_node_id): str(resource_id)
            for source_node_id, resource_id in self._db.execute(
                select(
                    LibraryReadableResource.source_node_id,
                    LibraryReadableResource.id,
                ).where(
                    LibraryReadableResource.book_id == book_id,
                    LibraryReadableResource.source_node_id.in_(source_node_ids),
                    LibraryReadableResource.enablement_state == "ENABLED",
                    LibraryReadableResource.import_state == "READY",
                )
            ).all()
        }
        return anchored

    @staticmethod
    def _node(
        node: LibrarySourceNode,
        *,
        metadata: LibrarySourceNodeMetadata | None = None,
        has_children: bool = False,
        resource_id: str | None,
        representative_resource_id: str | None = None,
    ) -> BookContentNode:
        return BookContentNode(
            source_node_id=node.id,
            library_id=node.library_id,
            parent_source_node_id=node.parent_id,
            name=node.name,
            title=(
                metadata.title.strip() if metadata and metadata.title else node.name
            ),
            description=metadata.description if metadata else None,
            physical_kind=node.physical_kind,
            size_bytes=node.observed_size_bytes,
            observed_at=node.observed_at,
            has_children=has_children,
            resource_id=resource_id,
            representative_resource_id=representative_resource_id or resource_id,
            cover_path=metadata.cover_path if metadata else None,
        )


__all__ = ["SqlAlchemyBookContentsQueries"]
