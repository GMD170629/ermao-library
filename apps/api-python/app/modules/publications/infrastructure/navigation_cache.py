"""SQLAlchemy adapter for the Publication navigation projection cache."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from app.models import ReadableResourceNavigationUnit
from app.modules.library.infrastructure.readable_resource_schema import (
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibrarySourceNode,
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
    def __init__(self, session: Session) -> None:
        self._session = session

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
        cache_exists, chapter_exists, count_exists = self._session.execute(
            select(
                exists().where(PublicationNavigationCache.resource_id == resource_id),
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
        return bool(cache_exists or chapter_exists or count_exists)


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
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_if_source_current(
        self,
        *,
        source: PublicationSource,
        identity: PublicationNavigationCacheIdentity,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> bool:
        """Acquire the write lock through source CAS, then replace atomically."""

        cas_result = self._source_cas_update(
            source=source,
            chapter_count=len(entries),
        )
        if not cas_result:
            return False

        self._delete_projection(resource_id=source.resource_id)
        self._session.add_all(
            [
                ReadableResourceNavigationUnit(
                    id=entry.id,
                    resource_id=source.resource_id,
                    asset_id=source.asset_id,
                    unit_type="chapter",
                    title=entry.title,
                    href=entry.href,
                    media_type=entry.media_type,
                    sort_order=entry.sort_order,
                    metadata_json=_navigation_metadata(entry),
                )
                for entry in entries
            ]
        )
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
        return True

    def invalidate_if_source_current(self, *, source: PublicationSource) -> bool:
        if not self._source_cas_update(source=source, chapter_count=None):
            return False
        self._delete_projection(resource_id=source.resource_id)
        return True

    def _source_cas_update(
        self,
        *,
        source: PublicationSource,
        chapter_count: int | None,
    ) -> bool:
        current_source = exists(
            select(LibraryResourceAsset.id)
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryResourceAsset.id == source.asset_id,
                LibraryResourceAsset.resource_id == source.resource_id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.observed_size_bytes == source.size_bytes,
                LibrarySourceNode.observed_mtime_ns == source.mtime_ms * 1_000_000,
            )
        )
        if not self._session.scalar(select(current_source)):
            return False
        metadata = self._session.get(
            LibraryReadableResourceMetadata,
            source.resource_id,
        )
        if metadata is not None:
            metadata.chapter_count = chapter_count
        return True

    def _delete_projection(self, *, resource_id: str) -> None:
        self._session.execute(
            delete(ReadableResourceNavigationUnit).where(
                ReadableResourceNavigationUnit.resource_id == resource_id,
                ReadableResourceNavigationUnit.unit_type == "chapter",
            )
        )
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
