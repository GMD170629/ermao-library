"""Library-owned persistence for materialized publication navigation."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.contracts.library_navigation import (
    LibraryNavigationEntry,
    LibraryNavigationMarker,
)
from app.models import ReadableResourceNavigationUnit
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetNavigation,
)


class SqlAlchemyLibraryNavigationProjection:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_marker(self, *, asset_id: str) -> LibraryNavigationMarker | None:
        marker = self._session.get(LibraryResourceAssetNavigation, asset_id)
        if marker is None:
            return None
        return LibraryNavigationMarker(
            asset_id=marker.asset_id,
            chapter_count=marker.chapter_count,
        )

    def replace(
        self,
        *,
        resource_id: str,
        asset_id: str,
        entries: tuple[LibraryNavigationEntry, ...],
    ) -> None:
        self._delete_units(resource_id=resource_id)
        self._session.add_all(
            [
                ReadableResourceNavigationUnit(
                    id=entry.id,
                    resource_id=resource_id,
                    asset_id=entry.asset_id,
                    unit_type="chapter",
                    title=entry.title,
                    href=entry.href,
                    media_type=entry.media_type,
                    sort_order=entry.sort_order,
                    metadata_json=entry.metadata_json,
                )
                for entry in entries
            ]
        )
        self._delete_markers(resource_id=resource_id)
        self._session.add(
            LibraryResourceAssetNavigation(
                asset_id=asset_id,
                chapter_count=len(entries),
            )
        )
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is not None:
            metadata.chapter_count = len(entries)

    def invalidate(self, *, resource_id: str) -> None:
        self._delete_units(resource_id=resource_id)
        self._delete_markers(resource_id=resource_id)
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is not None:
            metadata.chapter_count = None

    def invalidate_asset(self, *, resource_id: str, asset_id: str) -> None:
        self._session.execute(
            delete(ReadableResourceNavigationUnit).where(
                ReadableResourceNavigationUnit.resource_id == resource_id,
                ReadableResourceNavigationUnit.asset_id == asset_id,
            )
        )
        self._session.execute(
            delete(LibraryResourceAssetNavigation).where(
                LibraryResourceAssetNavigation.asset_id == asset_id
            )
        )
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is not None:
            metadata.chapter_count = None

    def _delete_units(self, *, resource_id: str) -> None:
        self._session.execute(
            delete(ReadableResourceNavigationUnit).where(
                ReadableResourceNavigationUnit.resource_id == resource_id,
                ReadableResourceNavigationUnit.unit_type == "chapter",
            )
        )

    def _delete_markers(self, *, resource_id: str) -> None:
        asset_ids = select(LibraryResourceAsset.id).where(
            LibraryResourceAsset.resource_id == resource_id
        )
        self._session.execute(
            delete(LibraryResourceAssetNavigation).where(
                LibraryResourceAssetNavigation.asset_id.in_(asset_ids)
            )
        )
