"""SQLAlchemy adapter for the Publication navigation projection cache."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.contracts.library_navigation import (
    LibraryNavigationEntry,
    LibraryNavigationProjection,
)
from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    PublicationNavigationCacheIdentity,
    PublicationNavigationCacheState,
    PublicationNavigationEntry,
    PublicationParserProfile,
)
from app.modules.publications.infrastructure.models import PublicationNavigationCache


class ConfiguredPublicationParserProfiles:
    """Resolve the current generator identity without parsing a publication."""

    def __init__(self, profiles: Mapping[str, PublicationParserProfile]) -> None:
        self._profiles = {
            source_format.lower(): profile
            for source_format, profile in profiles.items()
        }

    def resolve(self, *, source_format: str) -> PublicationParserProfile | None:
        return self._profiles.get(source_format.lower())


class SqlAlchemyPublicationNavigationCacheReader:
    def __init__(
        self,
        session: Session,
        library_projection: LibraryNavigationProjection,
    ) -> None:
        self._session = session
        self._library_projection = library_projection

    def find(self, *, resource_id: str) -> PublicationNavigationCacheState | None:
        cache = self._session.get(PublicationNavigationCache, resource_id)
        if cache is None:
            return None
        return PublicationNavigationCacheState(
            identity=PublicationNavigationCacheIdentity(
                resource_id=cache.resource_id,
                asset_id=cache.asset_id,
                source_size_bytes=cache.source_size_bytes,
                source_mtime_ms=cache.source_mtime_ms,
                parser=cache.parser,
                normalization=cache.normalization,
            ),
            chapter_count=cache.chapter_count,
            projection_version=cache.projection_version,
        )

    def has_materialized_projection(self, *, resource_id: str) -> bool:
        cache_exists = self._session.scalar(
            select(
                exists().where(PublicationNavigationCache.resource_id == resource_id)
            )
        )
        return bool(
            cache_exists
            or self._library_projection.has_materialized(resource_id=resource_id)
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
        identity: PublicationNavigationCacheIdentity,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> None:
        """Replace the materialized navigation projection atomically."""

        self._library_projection.replace(
            resource_id=source.resource_id,
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
        self._delete_cache(resource_id=source.resource_id)
        cache = self._session.get(PublicationNavigationCache, source.resource_id)
        if cache is None:
            cache = PublicationNavigationCache(resource_id=source.resource_id)
            self._session.add(cache)
        cache.asset_id = source.asset_id
        cache.source_size_bytes = identity.source_size_bytes
        cache.source_mtime_ms = identity.source_mtime_ms
        cache.parser = identity.parser
        cache.normalization = identity.normalization
        cache.projection_version = CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
        cache.chapter_count = len(entries)

    def invalidate(self, *, resource_id: str) -> None:
        self._library_projection.invalidate(resource_id=resource_id)
        self._delete_cache(resource_id=resource_id)

    def _delete_cache(self, *, resource_id: str) -> None:
        self._session.execute(
            delete(PublicationNavigationCache).where(
                PublicationNavigationCache.resource_id == resource_id
            )
        )


__all__ = [
    "ConfiguredPublicationParserProfiles",
    "SqlAlchemyPublicationNavigationCacheReader",
    "SqlAlchemyPublicationNavigationWriteRepository",
]
