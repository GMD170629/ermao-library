"""Lazily materialize the authoritative Publication TOC projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.modules.publications.application.navigation_ports import (
    PublicationNavigationLookupUnitOfWorkFactory,
    PublicationNavigationUnitOfWorkFactory,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationAdapter,
    PublicationSource,
)
from app.modules.publications.domain.model import (
    PublicationNotFoundError,
)
from app.modules.publications.domain.navigation import (
    PublicationNavigationMarkerState,
    flatten_publication_navigation,
)


class EnsurePublicationNavigationOutcome(StrEnum):
    CACHED = "CACHED"
    GENERATED = "GENERATED"


@dataclass(frozen=True, slots=True)
class EnsurePublicationNavigationResult:
    outcome: EnsurePublicationNavigationOutcome
    asset_id: str
    chapter_count: int


class EnsurePublicationNavigation:
    """Lazily generate and atomically publish a navigation projection."""

    def __init__(
        self,
        *,
        lookup_unit_of_work_factory: PublicationNavigationLookupUnitOfWorkFactory,
        publication_adapter: PublicationAdapter,
        unit_of_work_factory: PublicationNavigationUnitOfWorkFactory,
    ) -> None:
        self._lookup_unit_of_work_factory = lookup_unit_of_work_factory
        self._publication_adapter = publication_adapter
        self._unit_of_work_factory = unit_of_work_factory

    def execute(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> EnsurePublicationNavigationResult:
        source, marker = self._lookup(
            resource_id=resource_id,
            access_scope=access_scope,
        )

        if marker is not None:
            return EnsurePublicationNavigationResult(
                outcome=EnsurePublicationNavigationOutcome.CACHED,
                asset_id=source.asset_id,
                chapter_count=marker.chapter_count,
            )

        # A marker is keyed by the selected immutable asset.  A miss therefore
        # means either first access or an asset replacement; clear the old
        # resource projection before parsing so stale chapters cannot leak.
        self._invalidate(source.resource_id)

        publication = self._publication_adapter.open(source)
        entries = flatten_publication_navigation(
            resource_id=source.resource_id,
            publication=publication,
        )
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.navigation.replace(
                source=source,
                entries=entries,
            )
            unit_of_work.commit()
        return EnsurePublicationNavigationResult(
            outcome=EnsurePublicationNavigationOutcome.GENERATED,
            asset_id=source.asset_id,
            chapter_count=len(entries),
        )

    def _lookup(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> tuple[PublicationSource, PublicationNavigationMarkerState | None]:
        with self._lookup_unit_of_work_factory() as lookup:
            source = lookup.sources.find_source(
                resource_id=resource_id,
                access_scope=access_scope,
            )
            if source is None:
                raise PublicationNotFoundError
            marker = lookup.markers.find(asset_id=source.asset_id)
            return source, marker

    def _invalidate(self, resource_id: str) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.navigation.invalidate(resource_id=resource_id)
            unit_of_work.commit()


__all__ = [
    "EnsurePublicationNavigation",
    "EnsurePublicationNavigationOutcome",
    "EnsurePublicationNavigationResult",
]
