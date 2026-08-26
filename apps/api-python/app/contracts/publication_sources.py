"""Stable cross-capability contract for opening original publication sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PublicationAccessScope:
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicationSource:
    resource_id: str
    asset_id: str
    source_format: str
    path: str
    size_bytes: int
    mtime_ms: int
    title: str
    author: str | None
    library_root: str | None = None


class PublicationSourceRepository(Protocol):
    def find_source(
        self,
        *,
        resource_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource | None: ...
