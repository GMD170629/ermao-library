"""Paginated details for one readable resource on Book Detail."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Protocol

from app.core.natural_sort import natural_sort_key

REFLOWABLE_FORMATS = frozenset({"EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT"})
COMIC_FORMATS = frozenset({"CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR"})
AUDIO_FORMATS = frozenset({"AUDIO", "AUDIOBOOK", "AUDIOBOOK_DIR", "M4B", "M4A", "MP3"})


@dataclass(frozen=True, slots=True)
class ResourceDetailAccessScope:
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceDetailResource:
    id: str
    book_id: str
    format: str
    page_count: int | None
    progress: float
    current_href: str | None
    current_page_number: int | None
    current_position: int | None


@dataclass(frozen=True, slots=True)
class ResourceCurrentChapter:
    index: int
    title: str
    sort_order: int
    href: str | None


@dataclass(frozen=True, slots=True)
class ResourceDetailItem:
    id: str
    unit_type: str
    title: str
    sort_order: int
    asset_id: str | None = None
    href: str | None = None
    page_number: int | None = None
    media_type: str | None = None
    preview_url: str | None = None
    level: int | None = None
    duration_ms: int | None = None
    disc_number: int | None = None
    track_number: int | None = None
    metadata_json: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceAssetDetail:
    id: str
    role: str
    title: str
    media_type: str | None
    sort_key: str
    sort_order: int
    duration_ms: int | None
    disc_number: int | None
    track_number: int | None


@dataclass(frozen=True, slots=True)
class ResourceDetailPage:
    book_id: str
    resource_id: str
    units: tuple[ResourceDetailItem, ...]
    page: int
    page_size: int
    total: int
    progress: float
    current_href: str | None
    current_page_number: int | None
    current_chapter_index: int | None
    current_chapter_title: str | None
    current_chapter_sort_order: int | None


class ResourceDetailNotFoundError(Exception):
    """The actor cannot access the requested Book/Resource pair."""


class ResourceDetailQueries(Protocol):
    def get_resource(
        self,
        *,
        context: ResourceDetailAccessScope,
        book_id: str,
        resource_id: str,
    ) -> ResourceDetailResource | None: ...

    def list_navigation_units(
        self,
        *,
        resource_id: str,
        unit_type: str,
        limit: int,
        offset: int,
    ) -> tuple[tuple[ResourceDetailItem, ...], int]: ...

    def list_assets(self, *, resource_id: str) -> tuple[ResourceAssetDetail, ...]: ...

    def has_navigation_units(self, *, resource_id: str, unit_type: str) -> bool: ...

    def resolve_pdf_page_count(self, *, resource_id: str) -> int | None: ...

    def resolve_current_chapter(
        self,
        *,
        resource_id: str,
        current_href: str | None,
        current_position: int | None,
    ) -> ResourceCurrentChapter | None: ...


class ResourceNavigationPreparer(Protocol):
    def prepare(
        self, *, resource_id: str, context: ResourceDetailAccessScope
    ) -> None: ...


def _navigation_level(metadata_json: str | None) -> int | None:
    if not metadata_json:
        return None
    try:
        value = json.loads(metadata_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    level = value.get("level")
    return int(level) if isinstance(level, int) and level >= 0 else None


class ListResourceDetails:
    """Return one deterministic, bounded page for any readable resource format."""

    MAX_PAGE_SIZE = 100

    def __init__(
        self,
        queries: ResourceDetailQueries,
        navigation: ResourceNavigationPreparer,
    ) -> None:
        self._queries = queries
        self._navigation = navigation

    def execute(
        self,
        *,
        context: ResourceDetailAccessScope,
        book_id: str,
        resource_id: str,
        page: int,
        page_size: int,
    ) -> ResourceDetailPage:
        resource = self._queries.get_resource(
            context=context,
            book_id=book_id,
            resource_id=resource_id,
        )
        if resource is None:
            raise ResourceDetailNotFoundError

        normalized_page = max(1, page)
        normalized_size = min(self.MAX_PAGE_SIZE, max(1, page_size))
        offset = (normalized_page - 1) * normalized_size
        source_format = resource.format.strip().upper()
        current_chapter: ResourceCurrentChapter | None = None

        if source_format in REFLOWABLE_FORMATS:
            if not self._queries.has_navigation_units(
                resource_id=resource_id, unit_type="chapter"
            ):
                self._navigation.prepare(resource_id=resource_id, context=context)
            units, total = self._queries.list_navigation_units(
                resource_id=resource_id,
                unit_type="chapter",
                limit=normalized_size,
                offset=offset,
            )
            units = tuple(
                replace(unit, level=_navigation_level(unit.metadata_json))
                for unit in units
            )
            current_chapter = self._queries.resolve_current_chapter(
                resource_id=resource_id,
                current_href=resource.current_href,
                current_position=resource.current_position,
            )
        elif source_format in {"CBZ", "ZIP", "CBR", "RAR"}:
            units, total = self._queries.list_navigation_units(
                resource_id=resource_id,
                unit_type="page",
                limit=normalized_size,
                offset=offset,
            )
            units = tuple(
                replace(
                    unit,
                    page_number=unit.sort_order + 1,
                    preview_url=f"/api/resources/{resource_id}/previews/{unit.sort_order}",
                )
                for unit in units
            )
        elif source_format == "IMAGE_DIR":
            assets = self._ordered_assets(resource_id, roles={"PAGE"})
            total = len(assets)
            units = tuple(
                ResourceDetailItem(
                    id=asset.id,
                    unit_type="page",
                    title=asset.title,
                    sort_order=index,
                    asset_id=asset.id,
                    page_number=index + 1,
                    media_type=asset.media_type,
                    preview_url=f"/api/resources/{resource_id}/previews/{index}",
                )
                for index, asset in enumerate(
                    assets[offset : offset + normalized_size], start=offset
                )
            )
        elif source_format == "PDF":
            page_count = resource.page_count
            if page_count is None or page_count <= 0:
                page_count = self._queries.resolve_pdf_page_count(
                    resource_id=resource_id
                )
            total = max(0, page_count or 0)
            end = min(total, offset + normalized_size)
            units = tuple(
                ResourceDetailItem(
                    id=f"{resource_id}:page:{index + 1}",
                    unit_type="page",
                    title="",
                    sort_order=index,
                    page_number=index + 1,
                    media_type="application/pdf",
                    preview_url=f"/api/resources/{resource_id}/previews/{index}",
                )
                for index in range(offset, end)
            )
        elif source_format in AUDIO_FORMATS:
            assets = self._ordered_assets(resource_id, roles={"TRACK", "PRIMARY"})
            total = len(assets)
            units = tuple(
                ResourceDetailItem(
                    id=asset.id,
                    unit_type="track",
                    title=asset.title,
                    sort_order=index,
                    asset_id=asset.id,
                    media_type=asset.media_type,
                    duration_ms=asset.duration_ms,
                    disc_number=asset.disc_number,
                    track_number=asset.track_number,
                )
                for index, asset in enumerate(
                    assets[offset : offset + normalized_size], start=offset
                )
            )
        else:
            units, total = (), 0

        return ResourceDetailPage(
            book_id=book_id,
            resource_id=resource_id,
            units=units,
            page=normalized_page,
            page_size=normalized_size,
            total=total,
            progress=resource.progress,
            current_href=resource.current_href,
            current_page_number=resource.current_page_number,
            current_chapter_index=(
                current_chapter.index if current_chapter is not None else None
            ),
            current_chapter_title=(
                current_chapter.title if current_chapter is not None else None
            ),
            current_chapter_sort_order=(
                current_chapter.sort_order if current_chapter is not None else None
            ),
        )

    def _ordered_assets(
        self, resource_id: str, *, roles: set[str]
    ) -> tuple[ResourceAssetDetail, ...]:
        assets = (
            asset
            for asset in self._queries.list_assets(resource_id=resource_id)
            if asset.role.strip().upper() in roles
        )
        return tuple(
            sorted(
                assets,
                key=lambda asset: (
                    natural_sort_key(asset.sort_key or asset.title),
                    asset.id,
                ),
            )
        )


__all__ = [
    "AUDIO_FORMATS",
    "COMIC_FORMATS",
    "REFLOWABLE_FORMATS",
    "ListResourceDetails",
    "ResourceAssetDetail",
    "ResourceCurrentChapter",
    "ResourceDetailAccessScope",
    "ResourceDetailItem",
    "ResourceDetailNotFoundError",
    "ResourceDetailPage",
    "ResourceDetailQueries",
    "ResourceDetailResource",
    "ResourceNavigationPreparer",
]
