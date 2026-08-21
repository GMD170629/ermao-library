"""Read-only comic page-index contracts and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ResourcePageUnit:
    id: str
    resource_id: str
    asset_id: str | None
    unit_type: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    width: int | None
    height: int | None
    size: int | None
    metadata_json: str
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class ResourcePageSource:
    id: str
    path: str
    role: str
    import_state: str
    size_bytes: int
    sort_order: int
    mtime_ms: int


@dataclass(frozen=True)
class ResourcePageIndexProjection:
    """Database projection captured before any archive file is inspected."""

    resource_id: str
    resource_index: float | None
    persisted_pages: tuple[ResourcePageUnit, ...]
    sources: tuple[ResourcePageSource, ...]

    def comic_source(self) -> ResourcePageSource | None:
        return next(
            (source for source in self.sources if source.role == "PRIMARY"), None
        )


@dataclass(frozen=True)
class ResolvedResourcePageIndex:
    """Page data resolved without changing database state."""

    pages: tuple[ResourcePageUnit, ...]
    sources: tuple[ResourcePageSource, ...]

    def page(self, page_index: int) -> ResourcePageUnit | None:
        return next(
            (page for page in self.pages if page.sort_order == page_index),
            None,
        )

    def source_for(self, asset_id: str | None) -> ResourcePageSource | None:
        if asset_id is None:
            return None
        return next((source for source in self.sources if source.id == asset_id), None)


class ReadOnlyResourcePageIndex:
    """Resolve only the persisted page index prepared before API startup."""

    def execute(
        self,
        projection: ResourcePageIndexProjection,
    ) -> ResolvedResourcePageIndex:
        return ResolvedResourcePageIndex(
            pages=projection.persisted_pages,
            sources=projection.sources,
        )


__all__ = [
    "ReadOnlyResourcePageIndex",
    "ResolvedResourcePageIndex",
    "ResourcePageIndexProjection",
    "ResourcePageSource",
    "ResourcePageUnit",
]
