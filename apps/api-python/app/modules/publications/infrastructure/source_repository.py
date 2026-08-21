"""SQLAlchemy source lookup scoped to the authenticated actor."""

from __future__ import annotations

from sqlalchemy import false, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)


class SqlAlchemyPublicationSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_source(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource | None:
        visibility: ColumnElement[bool] = false()
        if access_scope.is_admin:
            visibility = LibraryReadableResource.id.is_not(None)
        elif access_scope.library_ids:
            visibility = LibraryBook.library_id.in_(access_scope.library_ids)
        row = self._session.execute(
            select(
                LibraryBook,
                LibraryBookMetadata,
                LibraryReadableResource,
                LibraryReadableResourceMetadata,
                LibraryResourceAsset,
                LibraryResourceAssetMetadata,
                LibrarySourceNode,
            )
            .join(
                LibraryReadableResource,
                LibraryReadableResource.book_id == LibraryBook.id,
            )
            .outerjoin(
                LibraryBookMetadata,
                LibraryBookMetadata.book_id == LibraryBook.id,
            )
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .join(
                LibraryResourceAsset,
                LibraryResourceAsset.resource_id == LibraryReadableResource.id,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
                visibility,
            )
            .order_by(
                LibraryResourceAsset.sequence_index,
                LibraryResourceAsset.sort_key,
                LibraryResourceAsset.created_at,
                LibraryResourceAsset.id,
            )
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        (
            _book,
            book_metadata,
            resource,
            resource_metadata,
            asset,
            _asset_metadata,
            source_node,
        ) = row
        return PublicationSource(
            resource_id=resource.id,
            asset_id=asset.id,
            source_format=resource.format.lower(),
            path=source_node.relative_path,
            size_bytes=source_node.observed_size_bytes or 0,
            mtime_ms=source_node.observed_mtime_ns // 1_000_000,
            title=(
                resource_metadata.title
                if resource_metadata is not None
                else book_metadata.title
                if book_metadata is not None
                else source_node.name
            ),
            author=book_metadata.author if book_metadata is not None else None,
        )
