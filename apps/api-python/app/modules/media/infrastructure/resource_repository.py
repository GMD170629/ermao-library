"""SQLAlchemy media adapter for READY ResourceAssets."""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.media_capabilities import resolve_asset_mime_type
from app.core.natural_sort import natural_sort_key
from app.models import (
    Library,
    LibraryBook,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.modules.media.application.resource_query import (
    MediaAssetResource,
    SourceNodeCoverResource,
)


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
                LibraryReadableResource,
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
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id == LibraryResourceAsset.resource_id,
            )
            .where(
                LibraryResourceAsset.id == asset_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).one_or_none()
        return self._asset_resource(row)

    def first_resource_asset(self, resource_id: str) -> MediaAssetResource | None:
        rows = self._session.execute(
            select(
                LibraryResourceAsset,
                LibrarySourceNode,
                LibraryResourceAssetMetadata,
                Library,
                LibraryReadableResource,
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
            .join(
                LibraryReadableResource,
                LibraryReadableResource.id == LibraryResourceAsset.resource_id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).all()
        row = min(
            rows,
            key=lambda value: (
                natural_sort_key(value[1].relative_path),
                value[0].id,
            ),
            default=None,
        )
        return self._asset_resource(row)

    def resource_cover_path(self, resource_id: str) -> str | None:
        return self._session.scalar(
            select(LibraryReadableResourceMetadata.cover_path).where(
                LibraryReadableResourceMetadata.resource_id == resource_id
            )
        )

    def source_node_cover(
        self, *, book_id: str, source_node_id: str
    ) -> SourceNodeCoverResource:
        book = self._session.get(LibraryBook, book_id)
        node = self._session.get(LibrarySourceNode, source_node_id)
        if book is None or node is None or node.physical_kind != "DIRECTORY":
            return SourceNodeCoverResource(found=False, path=None)
        root = self._session.get(LibrarySourceNode, book.source_node_id)
        if root is None or node.library_id != root.library_id:
            return SourceNodeCoverResource(found=False, path=None)
        root_relative = root.relative_path.rstrip("/")
        inside_root = (
            node.id == root.id
            or not root_relative
            or node.relative_path.startswith(f"{root_relative}/")
        )
        if not inside_root:
            return SourceNodeCoverResource(found=False, path=None)
        metadata = self._session.get(LibrarySourceNodeMetadata, node.id)
        return SourceNodeCoverResource(
            found=True,
            path=metadata.cover_path if metadata is not None else None,
        )

    @staticmethod
    def _asset_resource(
        row: object,
    ) -> MediaAssetResource | None:
        if row is None:
            return None
        asset, source_node, metadata, library, resource = cast(
            tuple[
                LibraryResourceAsset,
                LibrarySourceNode,
                LibraryResourceAssetMetadata | None,
                Library,
                LibraryReadableResource,
            ],
            row,
        )
        return MediaAssetResource(
            id=asset.id,
            path=source_node.relative_path,
            source_root=library.root_path,
            mime_type=resolve_asset_mime_type(
                resource_format=resource.format,
                asset_role=asset.role,
                filename=source_node.name,
                stored_mime_type=metadata.mime_type if metadata is not None else None,
            ),
        )
