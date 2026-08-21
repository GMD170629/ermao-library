"""SQLAlchemy media adapter for READY ResourceAssets."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Library,
    LibraryBookMetadata,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.media.application.resource_query import MediaAssetResource


class SqlAlchemyMediaResourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_asset(self, asset_id: str) -> MediaAssetResource | None:
        row = self._session.execute(
            select(
                LibraryResourceAsset,
                LibrarySourceNode,
                LibraryResourceAssetMetadata,
                Library,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .join(Library, Library.id == LibraryResourceAsset.library_id)
            .where(
                LibraryResourceAsset.id == asset_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).one_or_none()
        return self._asset_resource(row)

    def first_resource_asset(self, resource_id: str) -> MediaAssetResource | None:
        row = self._session.execute(
            select(
                LibraryResourceAsset,
                LibrarySourceNode,
                LibraryResourceAssetMetadata,
                Library,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .join(Library, Library.id == LibraryResourceAsset.library_id)
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
            .order_by(
                LibraryResourceAsset.sequence_index,
                LibraryResourceAsset.sort_key,
                LibraryResourceAsset.created_at,
                LibraryResourceAsset.id,
            )
            .limit(1)
        ).first()
        return self._asset_resource(row)

    def book_cover_path(self, book_id: str) -> str | None:
        return self._session.scalar(
            select(LibraryBookMetadata.cover_path).where(
                LibraryBookMetadata.book_id == book_id
            )
        )

    def resource_cover_path(self, resource_id: str) -> str | None:
        return self._session.scalar(
            select(LibraryReadableResourceMetadata.cover_path).where(
                LibraryReadableResourceMetadata.resource_id == resource_id
            )
        )

    @staticmethod
    def _asset_resource(
        row: tuple[
            LibraryResourceAsset,
            LibrarySourceNode,
            LibraryResourceAssetMetadata | None,
            Library,
        ]
        | None,
    ) -> MediaAssetResource | None:
        if row is None:
            return None
        asset, source_node, metadata, library = row
        return MediaAssetResource(
            id=asset.id,
            path=str(Path(library.root_path) / source_node.relative_path),
            mime_type=(
                metadata.mime_type
                if metadata is not None and metadata.mime_type
                else "application/octet-stream"
            ),
        )
