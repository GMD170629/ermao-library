"""Validate file moves against the existing Book/Resource placement rules."""

import hashlib
import json
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.library import Library
from app.modules.library.application.file_move_plans import MoveDestination, MoveSource
from app.modules.library.domain.book_placement import decide_book_anchor_for_resource
from app.modules.library.domain.file_moves import FileMoveError, MoveRequest
from app.modules.library.domain.organization_modes import TargetLibraryOrganizationMode
from app.modules.library.domain.source_nodes import SourceNodeRelativePath
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)


class SqlAlchemyMoveTopology:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _nodes(self, node: LibrarySourceNode) -> tuple[LibrarySourceNode, ...]:
        nodes = tuple(
            self._db.scalars(
                select(LibrarySourceNode)
                .where(
                    LibrarySourceNode.library_id == node.library_id,
                    or_(
                        LibrarySourceNode.id == node.id,
                        LibrarySourceNode.relative_path.startswith(
                            node.relative_path + "/", autoescape=True
                        ),
                    ),
                )
                .order_by(LibrarySourceNode.relative_path)
                .limit(20_001)
                .execution_options(populate_existing=True)
            )
        )
        if len(nodes) > 20_000:
            raise FileMoveError("INVENTORY_LIMIT")
        return nodes

    def source(self, node_id: str, library_ids: frozenset[str]) -> MoveSource:
        node = self._db.scalar(
            select(LibrarySourceNode)
            .where(
                LibrarySourceNode.id == node_id,
                LibrarySourceNode.library_id.in_(library_ids),
            )
            .execution_options(populate_existing=True)
        )
        if node is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        library = self._db.get(Library, node.library_id, populate_existing=True)
        if library is None or not library.enabled:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        nodes = self._nodes(node)
        ids = tuple(item.id for item in nodes)
        books = tuple(
            self._db.scalars(
                select(LibraryBook)
                .where(LibraryBook.source_node_id.in_(ids))
                .order_by(LibraryBook.id)
            )
        )
        resources = tuple(
            self._db.scalars(
                select(LibraryReadableResource)
                .where(LibraryReadableResource.source_node_id.in_(ids))
                .order_by(LibraryReadableResource.id)
            )
        )
        assets = tuple(
            self._db.scalars(
                select(LibraryResourceAsset)
                .where(LibraryResourceAsset.source_node_id.in_(ids))
                .order_by(LibraryResourceAsset.id)
            )
        )
        # Moving a partial aggregate across libraries would change its ownership.
        # Keep complete publication units as the admitted initial move boundary.
        book_ids = {book.id for book in books}
        resource_ids = {resource.id for resource in resources}
        if (
            not books
            or any(resource.book_id not in book_ids for resource in resources)
            or any(asset.resource_id not in resource_ids for asset in assets)
        ):
            raise FileMoveError("COMPLETE_BOOK_UNIT_REQUIRED")
        fingerprint = {
            "library": [library.id, library.root_path, library.organization_mode],
            "nodes": [
                (
                    item.id,
                    item.parent_id,
                    item.relative_path,
                    item.physical_kind,
                    item.observed_size_bytes,
                    item.observed_mtime_ns,
                )
                for item in nodes
            ],
            "books": [(book.id, book.source_node_id) for book in books],
            "resources": [
                (
                    resource.id,
                    resource.book_id,
                    resource.source_node_id,
                    resource.format,
                )
                for resource in resources
            ],
            "assets": [
                (asset.id, asset.resource_id, asset.source_node_id) for asset in assets
            ],
        }
        revision = hashlib.sha256(
            json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return MoveSource(
            node.id,
            library.id,
            node.relative_path,
            Path(library.root_path),
            revision,
            tuple(sorted(book_ids)),
        )

    def destination(
        self, source: MoveSource, request: MoveRequest, library_ids: frozenset[str]
    ) -> MoveDestination:
        library = self._db.scalar(
            select(Library)
            .where(
                Library.id == request.destination_library_id,
                Library.id.in_(library_ids),
                Library.enabled.is_(True),
            )
            .execution_options(populate_existing=True)
        )
        if library is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        node = self._db.get(LibrarySourceNode, source.node_id, populate_existing=True)
        if node is None:
            raise FileMoveError("RESOURCE_NOT_FOUND")
        nodes = {item.id: item for item in self._nodes(node)}
        books = tuple(
            self._db.scalars(
                select(LibraryBook).where(LibraryBook.id.in_(source.book_ids))
            )
        )
        resources = tuple(
            self._db.scalars(
                select(LibraryReadableResource).where(
                    LibraryReadableResource.book_id.in_(source.book_ids)
                )
            )
        )
        book_paths = {
            book.id: nodes[book.source_node_id].relative_path for book in books
        }

        def moved(path: str) -> str:
            if path != source.relative_path and not path.startswith(
                source.relative_path + "/"
            ):
                raise FileMoveError("COMPLETE_BOOK_UNIT_REQUIRED")
            return request.destination_relative_path + path[len(source.relative_path) :]

        for resource in resources:
            resource_node = nodes.get(resource.source_node_id)
            if resource_node is None:
                raise FileMoveError("COMPLETE_BOOK_UNIT_REQUIRED")
            target_path = moved(resource_node.relative_path)
            decision = decide_book_anchor_for_resource(
                organization_mode=TargetLibraryOrganizationMode(
                    library.organization_mode
                ),
                resource_relative_path=SourceNodeRelativePath(target_path),
                resource_is_directory=resource_node.physical_kind == "DIRECTORY",
            )
            expected_book_path = (
                target_path
                if decision.create_new_book_at_source_node
                else decision.resource_root_folder_relative_path
            )
            if expected_book_path != moved(book_paths[resource.book_id]):
                raise FileMoveError("BOOK_OWNERSHIP_WOULD_CHANGE")
        # Empty VOLUMES books must remain root directory books after a move.
        for book in books:
            if not any(resource.book_id == book.id for resource in resources) and (
                library.organization_mode != "VOLUMES"
                or "/" in moved(book_paths[book.id])
            ):
                raise FileMoveError("BOOK_OWNERSHIP_WOULD_CHANGE")
        return MoveDestination(
            library.id, Path(library.root_path), request.destination_relative_path
        )
