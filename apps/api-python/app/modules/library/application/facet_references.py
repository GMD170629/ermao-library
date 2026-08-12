"""Stable facet references used by mobile library navigation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.authorization import AuthorizationContext


@dataclass(frozen=True)
class LibraryFacetReference:
    id: str
    kind: str
    name: str


@dataclass(frozen=True)
class WorkFacetReferences:
    series: LibraryFacetReference | None
    authors: tuple[LibraryFacetReference, ...]


class LibraryFacetReferenceQueryPort(Protocol):
    def visible_facet(
        self,
        *,
        context: AuthorizationContext,
        kind: str,
        facet_id: str,
    ) -> LibraryFacetReference | None: ...

    def for_visible_work(self, work_id: str) -> WorkFacetReferences: ...
