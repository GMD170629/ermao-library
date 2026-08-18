"""Ports owned by the publication application layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.modules.publications.domain.model import (
    NormalizedPublication,
    PublicationResource,
)


@dataclass(frozen=True, slots=True)
class PublicationAccessScope:
    is_admin: bool
    can_view_manual_imports: bool
    library_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicationSource:
    volume_id: str
    file_id: str
    source_format: str
    path: str
    size_bytes: int
    mtime_ms: int
    title: str
    author: str | None


class PublicationSourceRepository(Protocol):
    def find_source(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource | None: ...


class PublicationAdapter(Protocol):
    def open(self, source: PublicationSource) -> NormalizedPublication: ...

    def read_resource(
        self,
        source: PublicationSource,
        href: str,
    ) -> PublicationResource: ...
