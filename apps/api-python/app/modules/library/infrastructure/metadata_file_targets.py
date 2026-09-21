"""Resolve file writes through canonical Book/Resource/Asset source identities."""

from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.library import Library
from app.modules.library.application.metadata_file_targets import MetadataFileTarget
from app.modules.library.domain.metadata_patch import MetadataPatchError
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryReadableResource,
    LibraryResourceAsset,
    LibrarySourceNode,
)


class SqlAlchemyMetadataFileTargets:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(
        self, node_id: str, library_ids: frozenset[str]
    ) -> MetadataFileTarget | None:
        row = self._db.execute(
            select(LibrarySourceNode, Library)
            .join(Library, Library.id == LibrarySourceNode.library_id)
            .where(
                LibrarySourceNode.id == node_id,
                Library.id.in_(library_ids),
                Library.enabled.is_(True),
            )
            .execution_options(populate_existing=True)
        ).one_or_none()
        if row is None:
            return None
        node, library = row
        assets = tuple(
            self._db.scalars(
                select(LibraryResourceAsset)
                .where(LibraryResourceAsset.source_node_id == node_id)
                .limit(2)
                .execution_options(populate_existing=True)
            )
        )
        resources = tuple(
            self._db.scalars(
                select(LibraryReadableResource)
                .where(
                    or_(
                        LibraryReadableResource.source_node_id == node_id,
                        LibraryReadableResource.id.in_(
                            {asset.resource_id for asset in assets}
                        ),
                    )
                )
                .limit(2)
                .execution_options(populate_existing=True)
            )
        )
        if len(resources) > 1 or len(assets) > 1:
            raise MetadataPatchError("AMBIGUOUS_FILE_TARGET")
        resource = resources[0] if resources else None
        book = self._db.scalar(
            select(LibraryBook).where(
                LibraryBook.library_id == library.id,
                LibraryBook.id == resource.book_id
                if resource
                else LibraryBook.source_node_id == node_id,
            )
        )
        if book is None:
            return None
        return MetadataFileTarget(
            node.id,
            library.id,
            Path(library.root_path),
            node.relative_path,
            node.physical_kind == "DIRECTORY",
            book.id,
            resource.id if resource else None,
            assets[0].id if assets else None,
            resource.format if resource else None,
        )
