"""Lazily materialize the authoritative Publication TOC projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.publications.application.navigation_ports import (
    PublicationNavigationLookupUnitOfWorkFactory,
    PublicationNavigationUnitOfWorkFactory,
    PublicationParserProfileResolver,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationUnsupportedError,
)
from app.modules.publications.domain.navigation import (
    CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION,
    PublicationNavigationCacheIdentity,
    PublicationNavigationCacheState,
    PublicationNavigationEntry,
    PublicationParserProfile,
    flatten_publication_navigation,
    publication_cache_identity,
)


class EnsurePublicationNavigationOutcome(StrEnum):
    CACHED = "CACHED"
    GENERATED = "GENERATED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class EnsurePublicationNavigationResult:
    outcome: EnsurePublicationNavigationOutcome
    chapter_count: int | None


@dataclass(frozen=True, slots=True)
class OpenPublicationNavigationResult:
    publication: NormalizedPublication
    navigation: EnsurePublicationNavigationResult


class EnsurePublicationNavigation:
    """Lazily generate and atomically publish a navigation projection."""

    def __init__(
        self,
        *,
        lookup_unit_of_work_factory: PublicationNavigationLookupUnitOfWorkFactory,
        publication_adapter: PublicationAdapter,
        profile_resolver: PublicationParserProfileResolver,
        unit_of_work_factory: PublicationNavigationUnitOfWorkFactory,
    ) -> None:
        self._lookup_unit_of_work_factory = lookup_unit_of_work_factory
        self._publication_adapter = publication_adapter
        self._profile_resolver = profile_resolver
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> EnsurePublicationNavigationResult:
        source, cached, has_projection = self._lookup(
            resource_id=resource_id,
            access_scope=access_scope,
        )

        profile = self._profile(source)
        if profile is None:
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.UNSUPPORTED,
                chapter_count=None,
            )
        if cached is not None and self._cache_matches(
            cached=cached,
            source=source,
            profile=profile,
        ):
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.CACHED,
                chapter_count=cached.chapter_count,
            )

        if has_projection:
            self._invalidate(source.resource_id)

        publication = self._publication_adapter.open(source)
        entries = flatten_publication_navigation(
            resource_id=source.resource_id,
            publication=publication,
        )
        actual_identity = publication_cache_identity(
            resource_id=source.resource_id,
            asset_id=source.asset_id,
            source_size_bytes=publication.revision.source_size_bytes,
            source_mtime_ms=publication.revision.source_mtime_ms,
            profile=profile,
        )
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.navigation.replace(
                source=source,
                identity=actual_identity,
                entries=entries,
            )
            unit_of_work.commit()
        return EnsurePublicationNavigationResult(
            outcome=EnsurePublicationNavigationOutcome.GENERATED,
            chapter_count=len(entries),
        )

    def open_and_ensure(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> OpenPublicationNavigationResult:
        """Open once and reuse that Publication when the manifest needs caching."""

        source, cached, has_projection = self._lookup(
            resource_id=resource_id,
            access_scope=access_scope,
        )
        profile = self._profile(source)
        if profile is None:
            raise PublicationUnsupportedError(source.source_format)
        cache_matches = self._cache_matches(
            cached=cached,
            source=source,
            profile=profile,
        )
        if not cache_matches and has_projection:
            self._invalidate(source.resource_id)

        try:
            publication = self._publication_adapter.open(source)
        except (PublicationCorruptError, PublicationUnsupportedError):
            if cache_matches:
                self._invalidate(source.resource_id)
            raise
        actual_identity = publication_cache_identity(
            resource_id=source.resource_id,
            asset_id=source.asset_id,
            source_size_bytes=publication.revision.source_size_bytes,
            source_mtime_ms=publication.revision.source_mtime_ms,
            profile=profile,
        )
        if cache_matches and cached is not None:
            return OpenPublicationNavigationResult(
                publication=publication,
                navigation=EnsurePublicationNavigationResult(
                    outcome=EnsurePublicationNavigationOutcome.CACHED,
                    chapter_count=cached.chapter_count,
                ),
            )

        entries = flatten_publication_navigation(
            resource_id=source.resource_id,
            publication=publication,
        )
        self._publish(source=source, identity=actual_identity, entries=entries)
        return OpenPublicationNavigationResult(
            publication=publication,
            navigation=EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.GENERATED,
                chapter_count=len(entries),
            ),
        )

    def _lookup(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> tuple[PublicationSource, PublicationNavigationCacheState | None, bool]:
        with self._lookup_unit_of_work_factory() as lookup:
            source = lookup.sources.find_source(
                resource_id=resource_id,
                access_scope=access_scope,
            )
            cached = lookup.cache.find(resource_id=resource_id)
            has_projection = lookup.cache.has_materialized_projection(
                resource_id=resource_id
            )
        if source is None:
            raise PublicationNotFoundError
        return source, cached, has_projection

    def _invalidate(self, resource_id: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.navigation.invalidate(resource_id=resource_id)
            unit_of_work.commit()

    def _publish(
        self,
        *,
        source: PublicationSource,
        identity: PublicationNavigationCacheIdentity,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.navigation.replace(
                source=source,
                identity=identity,
                entries=entries,
            )
            unit_of_work.commit()

    @staticmethod
    def _cache_matches(
        *,
        cached: PublicationNavigationCacheState | None,
        source: PublicationSource,
        profile: PublicationParserProfile,
    ) -> bool:
        return bool(
            cached is not None
            and cached.identity.resource_id == source.resource_id
            and cached.identity.asset_id == source.asset_id
            and cached.identity.parser == profile.parser
            and cached.identity.normalization == profile.normalization
            and cached.projection_version
            == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
        )

    def _profile(
        self,
        source: PublicationSource,
    ) -> PublicationParserProfile | None:
        return self._profile_resolver.resolve(source_format=source.source_format)


__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "OpenPublicationNavigationResult",
]
