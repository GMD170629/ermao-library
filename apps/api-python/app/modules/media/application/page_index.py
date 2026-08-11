"""Read-only comic page-index contracts and orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VolumePageUnit:
    id: str
    volume_id: str
    file_id: str | None
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
class VolumePageSource:
    id: str
    path: str
    kind: str
    mime_type: str
    size_bytes: int
    sort_order: int


@dataclass(frozen=True)
class VolumePageIndexProjection:
    """Database projection captured before any archive file is inspected."""

    volume_id: str
    volume_index: float | None
    persisted_pages: tuple[VolumePageUnit, ...]
    sources: tuple[VolumePageSource, ...]

    def comic_source(self) -> VolumePageSource | None:
        return next((source for source in self.sources if source.kind == "COMIC"), None)


@dataclass(frozen=True)
class ResolvedVolumePageIndex:
    """Page data resolved without changing database state."""

    pages: tuple[VolumePageUnit, ...]
    sources: tuple[VolumePageSource, ...]

    def page(self, page_index: int) -> VolumePageUnit | None:
        return next(
            (page for page in self.pages if page.sort_order == page_index),
            None,
        )

    def source_for(self, file_id: str | None) -> VolumePageSource | None:
        if file_id is None:
            return None
        return next((source for source in self.sources if source.id == file_id), None)


class ReadOnlyVolumePageIndex:
    """Resolve only the persisted page index prepared before API startup."""

    def execute(
        self,
        projection: VolumePageIndexProjection,
    ) -> ResolvedVolumePageIndex:
        return ResolvedVolumePageIndex(
            pages=projection.persisted_pages,
            sources=projection.sources,
        )


__all__ = [
    "ReadOnlyVolumePageIndex",
    "ResolvedVolumePageIndex",
    "VolumePageIndexProjection",
    "VolumePageSource",
    "VolumePageUnit",
]
