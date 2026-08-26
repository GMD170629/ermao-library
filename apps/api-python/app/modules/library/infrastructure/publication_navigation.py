"""Library-owned persistence for materialized publication navigation."""

from __future__ import annotations

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.contracts.library_navigation import LibraryNavigationEntry
from app.models import ReadableResourceNavigationUnit
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResourceMetadata,
)


class SqlAlchemyLibraryNavigationProjection:
    def __init__(self, session: Session) -> None:
        self._session = session

    def has_materialized(self, *, resource_id: str) -> bool:
        chapter_exists, count_exists = self._session.execute(
            select(
                exists().where(
                    ReadableResourceNavigationUnit.resource_id == resource_id,
                    ReadableResourceNavigationUnit.unit_type == "chapter",
                ),
                exists().where(
                    LibraryReadableResourceMetadata.resource_id == resource_id,
                    LibraryReadableResourceMetadata.chapter_count.is_not(None),
                ),
            )
        ).one()
        return bool(chapter_exists or count_exists)

    def replace(
        self,
        *,
        resource_id: str,
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
        metadata = self._session.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is not None:
            metadata.chapter_count = len(entries)

    def invalidate(self, *, resource_id: str) -> None:
        self._delete_units(resource_id=resource_id)
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
