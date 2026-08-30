"""Stable contract for Library-owned publication navigation projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class LibraryNavigationEntry:
    id: str
    asset_id: str
    title: str
    href: str
    media_type: str | None
    sort_order: int
    metadata_json: str


@dataclass(frozen=True, slots=True)
class LibraryNavigationMarker:
    """Successful navigation materialization for one immutable resource asset."""

    asset_id: str
    chapter_count: int


class LibraryNavigationProjection(Protocol):
    def find_marker(self, *, asset_id: str) -> LibraryNavigationMarker | None: ...

    def replace(
        self,
        *,
        resource_id: str,
        asset_id: str,
        entries: tuple[LibraryNavigationEntry, ...],
    ) -> None: ...

    def invalidate(self, *, resource_id: str) -> None: ...

    def invalidate_asset(self, *, resource_id: str, asset_id: str) -> None: ...
