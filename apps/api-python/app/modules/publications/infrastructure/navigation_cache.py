"""SQLAlchemy adapter for the Publication navigation projection cache."""

from __future__ import annotations

import json
from collections.abc import Mapping

from sqlalchemy import delete, exists, select, update
from sqlalchemy.orm import Session

from app.models.library import LibraryFile, LibraryReadingUnit, LibraryVolume
from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    PublicationNavigationCacheIdentity,
    PublicationNavigationCacheState,
    PublicationNavigationEntry,
    PublicationParserProfile,
    canonical_original_file_hash,
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

    def find(self, *, volume_id: str) -> PublicationNavigationCacheState | None:
        cache = self._session.get(PublicationNavigationCache, volume_id)
        if cache is None:
            return None
        return PublicationNavigationCacheState(
            identity=PublicationNavigationCacheIdentity(
                volume_id=cache.volume_id,
                file_id=cache.file_id,
                original_file_hash=cache.original_file_hash,
                parser=cache.parser,
                normalization=cache.normalization,
            ),
            chapter_count=cache.chapter_count,
            projection_version=cache.projection_version,
        )

    def has_materialized_projection(self, *, volume_id: str) -> bool:
        cache_exists, chapter_exists, count_exists = self._session.execute(
            select(
                exists().where(PublicationNavigationCache.volume_id == volume_id),
                exists().where(
                    LibraryReadingUnit.volume_id == volume_id,
                    LibraryReadingUnit.unit_type == "chapter",
                ),
                exists().where(
                    LibraryVolume.id == volume_id,
                    LibraryVolume.chapter_count.is_not(None),
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

        self._delete_projection(volume_id=source.volume_id)
        self._session.add_all(
            [
                LibraryReadingUnit(
                    id=entry.id,
                    volume_id=source.volume_id,
                    file_id=source.file_id,
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
        cache = self._session.get(PublicationNavigationCache, source.volume_id)
        if cache is None:
            cache = PublicationNavigationCache(volume_id=source.volume_id)
            self._session.add(cache)
        cache.file_id = source.file_id
        cache.original_file_hash = canonical_original_file_hash(
            identity.original_file_hash
        )
        cache.parser = identity.parser
        cache.normalization = identity.normalization
        cache.projection_version = CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
        cache.chapter_count = len(entries)
        return True

    def invalidate_if_source_current(self, *, source: PublicationSource) -> bool:
        if not self._source_cas_update(source=source, chapter_count=None):
            return False
        self._delete_projection(volume_id=source.volume_id)
        return True

    def _source_cas_update(
        self,
        *,
        source: PublicationSource,
        chapter_count: int | None,
    ) -> bool:
        first_file_id = (
            select(LibraryFile.id)
            .where(LibraryFile.volume_id == LibraryVolume.id)
            .order_by(
                LibraryFile.sort_order.asc(),
                LibraryFile.created_at.asc(),
                LibraryFile.id.asc(),
            )
            .limit(1)
            .correlate(LibraryVolume)
            .scalar_subquery()
        )
        current_source = exists(
            select(LibraryFile.id).where(
                LibraryFile.id == source.file_id,
                LibraryFile.volume_id == source.volume_id,
                (
                    LibraryFile.full_hash == source.full_hash
                    if source.full_hash is not None
                    else LibraryFile.full_hash.is_(None)
                ),
            )
        )
        updated_volume_id = self._session.scalar(
            update(LibraryVolume)
            .where(
                LibraryVolume.id == source.volume_id,
                first_file_id == source.file_id,
                current_source,
            )
            .values(chapter_count=chapter_count)
            .returning(LibraryVolume.id)
        )
        return updated_volume_id == source.volume_id

    def _delete_projection(self, *, volume_id: str) -> None:
        self._session.execute(
            delete(LibraryReadingUnit).where(
                LibraryReadingUnit.volume_id == volume_id,
                LibraryReadingUnit.unit_type == "chapter",
            )
        )
        self._session.execute(
            delete(PublicationNavigationCache).where(
                PublicationNavigationCache.volume_id == volume_id
            )
        )


__all__ = [
    "ConfiguredPublicationParserProfiles",
    "SqlAlchemyPublicationNavigationCacheReader",
    "SqlAlchemyPublicationNavigationWriteRepository",
]
