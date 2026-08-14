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
    canonical_original_file_hash,
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
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> EnsurePublicationNavigationResult:
        source, cached, has_projection = self._lookup(
            volume_id=volume_id,
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
        if source.full_hash is not None and (
            canonical_original_file_hash(source.full_hash)
            != canonical_original_file_hash(publication.fingerprint.original_file_hash)
        ):
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.SOURCE_CHANGED,
                chapter_count=None,
            )
        entries = flatten_publication_navigation(
            volume_id=source.volume_id,
            publication=publication,
        )
        actual_identity = publication_cache_identity(
            volume_id=source.volume_id,
            file_id=source.file_id,
            original_file_hash=publication.fingerprint.original_file_hash,
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
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> OpenPublicationNavigationResult:
        """Open once and reuse that Publication when the manifest needs caching."""

        source, cached, has_projection = self._lookup(
            volume_id=volume_id,
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
            volume_id=source.volume_id,
            file_id=source.file_id,
            original_file_hash=publication.fingerprint.original_file_hash,
            profile=profile,
        )
        if source.full_hash is not None and (
            actual_identity.original_file_hash
            != canonical_original_file_hash(source.full_hash)
        ):
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
            volume_id=source.volume_id,
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
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> tuple[PublicationSource, PublicationNavigationCacheState | None, bool]:
        with self._lookup_unit_of_work_factory() as lookup:
            source = lookup.sources.find_source(
                volume_id=volume_id,
                access_scope=access_scope,
            )
            cached = lookup.cache.find(volume_id=volume_id)
            has_projection = lookup.cache.has_materialized_projection(
                volume_id=volume_id
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
    ) -> PublicationNavigationCacheIdentity | None:
        if source.full_hash is None:
            return None
        return publication_cache_identity(
            volume_id=source.volume_id,
            file_id=source.file_id,
            original_file_hash=source.full_hash,
            profile=profile,
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
    "PublicationNavigationSourceChangedError",
]
