"""Reader-owned adapter for the version-neutral resource catalog.

The catalog is shared by Reader protocol versions, while progress, mutation,
and bookmark persistence remains version-owned.  Keeping this adapter free of
the v4 progress models prevents a newer protocol from accidentally reading
legacy state.
"""

from __future__ import annotations

from sqlalchemy import false, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.contracts.media_capabilities import resolve_asset_mime_type
from app.core.natural_sort import natural_sort_key
from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
    ReadableResourceNavigationUnit,
)
from app.modules.library.public import (
    AssetTitleCandidate,
    resolve_asset_display_titles,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderAssetDto,
    ReaderBookDto,
    ReaderNavigationUnitDto,
    ReaderResourceContextDto,
    ReaderResourceDto,
)


def _resource_dto(
    resource: LibraryReadableResource,
    resource_metadata: LibraryReadableResourceMetadata | None,
    book_metadata: LibraryBookMetadata | None,
    source_node: LibrarySourceNode,
) -> ReaderResourceDto:
    title = (
        resource_metadata.title
        if resource_metadata is not None
        else book_metadata.title
        if book_metadata is not None
        else source_node.name
    )
    return ReaderResourceDto(
        id=resource.id,
        book_id=resource.book_id,
        source_node_id=resource.source_node_id,
        title=title,
        format=resource.format,
        source_format=resource.format.strip().upper(),
        resource_index=(
            resource_metadata.resource_index if resource_metadata is not None else None
        ),
        sort_order=(
            int(resource_metadata.resource_index)
            if resource_metadata is not None
            and resource_metadata.resource_index is not None
            else 0
        ),
        page_count=(
            resource_metadata.page_count if resource_metadata is not None else None
        ),
        chapter_count=(
            resource_metadata.chapter_count if resource_metadata is not None else None
        ),
        duration_ms=(
            resource_metadata.duration_ms if resource_metadata is not None else None
        ),
        track_count=(
            resource_metadata.track_count if resource_metadata is not None else None
        ),
        updated_at=resource.updated_at,
    )


def _book_dto(book: LibraryBook, metadata: LibraryBookMetadata | None) -> ReaderBookDto:
    return ReaderBookDto(
        id=book.id,
        title=metadata.title if metadata is not None else book.id,
        author=metadata.author if metadata is not None else None,
    )


class SqlAlchemyReaderResourceCatalogRepository:
    """Read-only resource/catalog adapter used by all Reader versions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_context(self, resource_id: str) -> ReaderResourceContextDto | None:
        return self._get_context(
            resource_id,
            LibraryReadableResource.id.is_not(None),
        )

    def get_visible_context(
        self,
        resource_id: str,
        access_scope: ReaderAccessScope,
    ) -> ReaderResourceContextDto | None:
        visibility: ColumnElement[bool] = LibraryReadableResource.id.is_not(None)
        if not access_scope.is_admin:
            visibility = (
                LibraryReadableResource.library_id.in_(access_scope.library_ids)
                if access_scope.library_ids
                else false()
            )
        return self._get_context(resource_id, visibility)

    def _get_context(
        self,
        resource_id: str,
        visibility: ColumnElement[bool],
    ) -> ReaderResourceContextDto | None:
        row = self._session.execute(
            select(
                LibraryBook,
                LibraryBookMetadata,
                LibraryReadableResource,
                LibraryReadableResourceMetadata,
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
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                visibility,
            )
        ).one_or_none()
        if row is None:
            return None
        book, book_metadata, resource, resource_metadata, source_node = row
        return ReaderResourceContextDto(
            book=_book_dto(book, book_metadata),
            resource=_resource_dto(
                resource, resource_metadata, book_metadata, source_node
            ),
        )

    def list_visible_resources_for_book(
        self, book_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderResourceDto]:
        visibility: ColumnElement[bool] = LibraryBook.id.is_not(None)
        if not access_scope.is_admin:
            visibility = (
                LibraryBook.library_id.in_(access_scope.library_ids)
                if access_scope.library_ids
                else false()
            )
        rows = self._session.execute(
            select(
                LibraryReadableResource,
                LibraryReadableResourceMetadata,
                LibraryBookMetadata,
                LibrarySourceNode,
            )
            .join(LibraryBook, LibraryBook.id == LibraryReadableResource.book_id)
            .outerjoin(
                LibraryReadableResourceMetadata,
                LibraryReadableResourceMetadata.resource_id
                == LibraryReadableResource.id,
            )
            .outerjoin(
                LibraryBookMetadata,
                LibraryBookMetadata.book_id == LibraryBook.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryReadableResource.source_node_id,
            )
            .where(
                LibraryReadableResource.book_id == book_id,
                LibraryReadableResource.enablement_state == "ENABLED",
                LibraryReadableResource.import_state == "READY",
                visibility,
            )
        ).all()
        resources = [
            _resource_dto(resource, resource_metadata, book_metadata, source_node)
            for resource, resource_metadata, book_metadata, source_node in rows
        ]
        return sorted(
            resources, key=lambda item: (item.sort_order, item.updated_at, item.id)
        )

    def list_assets(self, resource_id: str) -> list[ReaderAssetDto]:
        resource_format = self._session.scalar(
            select(LibraryReadableResource.format).where(
                LibraryReadableResource.id == resource_id
            )
        )
        if resource_format is None:
            return []
        rows = self._session.execute(
            select(
                LibraryResourceAsset,
                LibrarySourceNode,
                LibraryResourceAssetMetadata,
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
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
        ).all()
        ordered_rows = sorted(
            rows,
            key=lambda row: (
                row[2].disc_number if row[2] and row[2].disc_number else 1,
                row[2].track_number
                if row[2] and row[2].track_number is not None
                else 10**9,
                natural_sort_key(row[1].relative_path),
                row[0].id,
            ),
        )
        titles = resolve_asset_display_titles(
            AssetTitleCandidate(
                asset_id=asset.id,
                metadata_title=(
                    asset_metadata.title if asset_metadata is not None else None
                ),
                source_filename=source_node.name,
            )
            for asset, source_node, asset_metadata in ordered_rows
        )
        return [
            ReaderAssetDto(
                id=asset.id,
                title=titles[asset.id],
                resource_id=asset.resource_id,
                source_node_id=asset.source_node_id,
                role=asset.role,
                mime_type=resolve_asset_mime_type(
                    resource_format=resource_format,
                    asset_role=asset.role,
                    filename=source_node.name,
                    stored_mime_type=(
                        asset_metadata.mime_type if asset_metadata is not None else None
                    ),
                ),
                size_bytes=source_node.observed_size_bytes or 0,
                duration_ms=(
                    asset_metadata.duration_ms if asset_metadata is not None else None
                ),
                disc_number=(
                    asset_metadata.disc_number if asset_metadata is not None else None
                ),
                track_number=(
                    asset_metadata.track_number if asset_metadata is not None else None
                ),
                sort_order=sort_order,
                mtime_ms=source_node.observed_mtime_ns // 1_000_000,
                codec=asset_metadata.codec if asset_metadata is not None else None,
            )
            for sort_order, (asset, source_node, asset_metadata) in enumerate(
                ordered_rows
            )
        ]

    def list_navigation_units(self, resource_id: str) -> list[ReaderNavigationUnitDto]:
        rows = self._session.scalars(
            select(ReadableResourceNavigationUnit)
            .where(ReadableResourceNavigationUnit.resource_id == resource_id)
            .order_by(
                ReadableResourceNavigationUnit.sort_order,
                ReadableResourceNavigationUnit.id,
            )
        ).all()
        return [
            ReaderNavigationUnitDto(
                id=unit.id,
                resource_id=unit.resource_id,
                asset_id=unit.asset_id,
                unit_type=unit.unit_type,
                title=unit.title,
                href=unit.href,
                media_type=unit.media_type,
                sort_order=unit.sort_order,
                start_ms=unit.start_ms,
                end_ms=unit.end_ms,
                duration_ms=unit.duration_ms,
                metadata_json=unit.metadata_json,
            )
            for unit in rows
        ]
