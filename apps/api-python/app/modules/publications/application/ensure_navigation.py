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
    SOURCE_CHANGED = "SOURCE_CHANGED"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class EnsurePublicationNavigationResult:
    outcome: EnsurePublicationNavigationOutcome
    chapter_count: int | None


@dataclass(frozen=True, slots=True)
class OpenPublicationNavigationResult:
    publication: NormalizedPublication
    navigation: EnsurePublicationNavigationResult


class PublicationNavigationSourceChangedError(Exception):
    """The selected source changed while its navigation was being generated."""


class EnsurePublicationNavigation:
    """Generate outside a transaction and atomically publish after source CAS."""

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
        expected_identity = self._expected_identity(source, profile)
        if expected_identity is not None and (
            cached is not None
            and cached.identity == expected_identity
            and cached.projection_version
            == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
        ):
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.CACHED,
                chapter_count=cached.chapter_count,
            )

        if has_projection and not self._invalidate(source):
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.SOURCE_CHANGED,
                chapter_count=None,
            )

        publication = self._publication_adapter.open(source)
        if not _source_matches_publication(source, publication):
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.SOURCE_CHANGED,
                chapter_count=None,
            )
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
            replaced = unit_of_work.navigation.replace_if_source_current(
                source=source,
                identity=actual_identity,
                entries=entries,
            )
            if replaced:
                unit_of_work.commit()
        return EnsurePublicationNavigationResult(
            outcome=(
                EnsurePublicationNavigationOutcome.GENERATED
                if replaced
                else EnsurePublicationNavigationOutcome.SOURCE_CHANGED
            ),
            chapter_count=len(entries) if replaced else None,
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
        expected_identity = self._expected_identity(source, profile)
        cache_matches = expected_identity is not None and (
            cached is not None
            and cached.identity == expected_identity
            and cached.projection_version
            == CURRENT_PUBLICATION_NAVIGATION_PROJECTION_VERSION
        )
        if not cache_matches and has_projection and not self._invalidate(source):
            raise PublicationNavigationSourceChangedError

        try:
            publication = self._publication_adapter.open(source)
        except (PublicationCorruptError, PublicationUnsupportedError):
            if cache_matches:
                self._invalidate(source)
            raise
        actual_identity = publication_cache_identity(
            resource_id=source.resource_id,
            asset_id=source.asset_id,
            source_size_bytes=publication.revision.source_size_bytes,
            source_mtime_ms=publication.revision.source_mtime_ms,
            profile=profile,
        )
        if not _source_matches_publication(source, publication):
            if cache_matches:
                self._invalidate(source)
            raise PublicationNavigationSourceChangedError

        if cache_matches and cached is not None and cached.identity == actual_identity:
            return OpenPublicationNavigationResult(
                publication=publication,
                navigation=EnsurePublicationNavigationResult(
                    outcome=EnsurePublicationNavigationOutcome.CACHED,
                    chapter_count=cached.chapter_count,
                ),
            )

        if cache_matches and not self._invalidate(source):
            raise PublicationNavigationSourceChangedError
        entries = flatten_publication_navigation(
            resource_id=source.resource_id,
            publication=publication,
        )
        if not self._publish(source=source, identity=actual_identity, entries=entries):
            raise PublicationNavigationSourceChangedError
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

    def _invalidate(self, source: PublicationSource) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            invalidated = unit_of_work.navigation.invalidate_if_source_current(
                source=source
            )
            if invalidated:
                unit_of_work.commit()
        return invalidated

    def _publish(
        self,
        *,
        source: PublicationSource,
        identity: PublicationNavigationCacheIdentity,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> bool:
        with self._unit_of_work_factory() as unit_of_work:
            replaced = unit_of_work.navigation.replace_if_source_current(
                source=source,
                identity=identity,
                entries=entries,
            )
            if replaced:
                unit_of_work.commit()
        return replaced

    def _expected_identity(
        self,
        source: PublicationSource,
        profile: PublicationParserProfile,
    ) -> PublicationNavigationCacheIdentity:
        return publication_cache_identity(
            resource_id=source.resource_id,
            asset_id=source.asset_id,
            source_size_bytes=source.size_bytes,
            source_mtime_ms=source.mtime_ms,
            profile=profile,
        )

    def _profile(
        self,
        source: PublicationSource,
    ) -> PublicationParserProfile | None:
        return self._profile_resolver.resolve(source_format=source.source_format)


def _source_matches_publication(
    source: PublicationSource,
    publication: NormalizedPublication,
) -> bool:
    return (
        publication.revision.source_size_bytes == source.size_bytes
        and publication.revision.source_mtime_ms == source.mtime_ms
    )


__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
    "OpenPublicationNavigationResult",
    "PublicationNavigationSourceChangedError",
]
