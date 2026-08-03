"""Application contracts for publishing the authorized library catalog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, cast

from app.core.authorization import AuthorizationContext

CATALOG_FACET_KINDS = frozenset({"AUTHOR", "SERIES", "TAG"})
CatalogFacetKind = Literal["AUTHOR", "SERIES", "TAG"]
CatalogSort = Literal["title", "recent"]


@dataclass(frozen=True)
class CatalogFile:
    id: str
    mime_type: str
    size_bytes: int
    updated_at: datetime


@dataclass(frozen=True)
class CatalogVolume:
    id: str
    title: str
    media_kind: str
    format: str
    volume_index: float | None
    sort_order: int
    description: str | None
    language: str | None
    publisher: str | None
    published_at: datetime | None
    identifier: str | None
    isbn: str | None
    page_count: int | None
    has_cover: bool
    file: CatalogFile
    updated_at: datetime


@dataclass(frozen=True)
class CatalogWorkFacet:
    id: str
    kind: CatalogFacetKind
    name: str


@dataclass(frozen=True)
class CatalogWork:
    id: str
    title: str
    author: str | None
    description: str | None
    series_name: str | None
    series_index: float | None
    has_cover: bool
    facets: tuple[CatalogWorkFacet, ...]
    volumes: tuple[CatalogVolume, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CatalogWorkFilter:
    search: str = ""
    facet_kind: CatalogFacetKind | None = None
    facet_id: str | None = None
    work_ids: tuple[str, ...] | None = None
    sort: CatalogSort = "title"


@dataclass(frozen=True)
class CatalogWorkPage:
    works: tuple[CatalogWork, ...]
    total: int
    page: int
    page_size: int
    updated_at: datetime | None


@dataclass(frozen=True)
class CatalogFacet:
    id: str
    kind: CatalogFacetKind
    name: str
    normalized_name: str
    work_count: int
    updated_at: datetime


@dataclass(frozen=True)
class CatalogFacetPage:
    facets: tuple[CatalogFacet, ...]
    total: int
    page: int
    page_size: int
    updated_at: datetime | None


class CatalogQueryPort(Protocol):
    def list_works(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogWorkFilter,
        page: int,
        page_size: int,
    ) -> CatalogWorkPage: ...

    def get_work(
        self,
        *,
        context: AuthorizationContext,
        work_id: str,
    ) -> CatalogWork | None: ...

    def list_facets(
        self,
        *,
        context: AuthorizationContext,
        kind: CatalogFacetKind,
        search: str,
        page: int,
        page_size: int,
    ) -> CatalogFacetPage: ...


@dataclass(frozen=True)
class ListCatalogWorks:
    query: CatalogQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogWorkFilter | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> CatalogWorkPage:
        normalized_filters = filters or CatalogWorkFilter()
        if (normalized_filters.facet_kind is None) != (
            normalized_filters.facet_id is None
        ):
            raise ValueError("facet kind and id must be provided together")
        return self.query.list_works(
            context=context,
            filters=CatalogWorkFilter(
                search=normalized_filters.search.strip(),
                facet_kind=normalized_filters.facet_kind,
                facet_id=normalized_filters.facet_id,
                work_ids=normalized_filters.work_ids,
                sort=normalized_filters.sort,
            ),
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )


@dataclass(frozen=True)
class GetCatalogWork:
    query: CatalogQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        work_id: str,
    ) -> CatalogWork | None:
        normalized_id = work_id.strip()
        if not normalized_id:
            return None
        return self.query.get_work(context=context, work_id=normalized_id)


@dataclass(frozen=True)
class ListCatalogFacets:
    query: CatalogQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        kind: str,
        search: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> CatalogFacetPage:
        normalized_kind = kind.strip().upper()
        if normalized_kind not in CATALOG_FACET_KINDS:
            raise ValueError("invalid catalog facet kind")
        return self.query.list_facets(
            context=context,
            kind=cast(CatalogFacetKind, normalized_kind),
            search=search.strip(),
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )
