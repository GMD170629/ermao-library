"""SQLAlchemy adapter for the Publication navigation projection cache."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.contracts.library_navigation import (
    LibraryNavigationEntry,
    LibraryNavigationProjection,
)
from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.navigation import (
    PublicationNavigationEntry,
    PublicationNavigationMarkerState,
)


class SqlAlchemyPublicationNavigationMarkerReader:
    def __init__(
        self,
        session: Session,
        library_projection: LibraryNavigationProjection,
    ) -> None:
        self._session = session
        self._library_projection = library_projection

    def find(self, *, asset_id: str) -> PublicationNavigationMarkerState | None:
        marker = self._library_projection.find_marker(asset_id=asset_id)
        if marker is None:
            return None
        return PublicationNavigationMarkerState(
            asset_id=marker.asset_id,
            chapter_count=marker.chapter_count,
        )


def _navigation_metadata(entry: PublicationNavigationEntry) -> str:
    return json.dumps(
        {
            "exactNavigation": True,
            "hrefBase": "publication-root",
            "level": entry.level,
            "navigationKey": entry.navigation_key,
            "path": list(entry.path),
            "readingOrderPosition": entry.reading_order_position,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class SqlAlchemyPublicationNavigationWriteRepository:
    def __init__(
        self,
        session: Session,
        library_projection: LibraryNavigationProjection,
    ) -> None:
        self._session = session
        self._library_projection = library_projection

    def replace(
        self,
        *,
        source: PublicationSource,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> None:
        """Replace the materialized navigation projection atomically."""

        self._library_projection.replace(
            resource_id=source.resource_id,
            asset_id=source.asset_id,
            entries=tuple(
                LibraryNavigationEntry(
                    id=entry.id,
                    asset_id=source.asset_id,
                    title=entry.title,
                    href=entry.href,
                    media_type=entry.media_type,
                    sort_order=entry.sort_order,
                    metadata_json=_navigation_metadata(entry),
                )
                for entry in entries
            ),
        )

    def invalidate(self, *, resource_id: str) -> None:
        self._library_projection.invalidate(resource_id=resource_id)


__all__ = [
    "SqlAlchemyPublicationNavigationMarkerReader",
    "SqlAlchemyPublicationNavigationWriteRepository",
]
