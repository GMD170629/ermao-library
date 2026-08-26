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


class LibraryNavigationProjection(Protocol):
    def has_materialized(self, *, resource_id: str) -> bool: ...

    def replace(
        self,
        *,
        resource_id: str,
        entries: tuple[LibraryNavigationEntry, ...],
    ) -> None: ...

    def invalidate(self, *, resource_id: str) -> None: ...
