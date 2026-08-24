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
class CatalogAsset:
    id: str
    mime_type: str
    size_bytes: int
    updated_at: datetime


@dataclass(frozen=True)
class CatalogResource:
    id: str
    title: str
    format: str
    resource_index: float | None
    sort_order: int
    description: str | None
    language: str | None
    publisher: str | None
    published_at: datetime | None
    identifier: str | None
    isbn: str | None
    page_count: int | None
    has_cover: bool
    asset: CatalogAsset
    updated_at: datetime


@dataclass(frozen=True)
class CatalogBookFacet:
    id: str
    kind: CatalogFacetKind
    name: str


@dataclass(frozen=True)
class CatalogBook:
    id: str
    title: str
    author: str | None
    description: str | None
    series_name: str | None
    series_index: float | None
    has_cover: bool
    facets: tuple[CatalogBookFacet, ...]
    resources: tuple[CatalogResource, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CatalogBookFilter:
    search: str = ""
    facet_kind: CatalogFacetKind | None = None
    facet_id: str | None = None
    book_ids: tuple[str, ...] | None = None
    sort: CatalogSort = "title"


@dataclass(frozen=True)
class CatalogBookPage:
    books: tuple[CatalogBook, ...]
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
    aliases: tuple[str, ...]
    book_count: int
    updated_at: datetime


@dataclass(frozen=True)
class CatalogFacetPage:
    facets: tuple[CatalogFacet, ...]
    total: int
    page: int
    page_size: int
    updated_at: datetime | None


class CatalogQueryPort(Protocol):
    def list_books(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogBookFilter,
        page: int,
        page_size: int,
    ) -> CatalogBookPage: ...

    def get_book(
        self,
        *,
        context: AuthorizationContext,
        book_id: str,
    ) -> CatalogBook | None: ...

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
class ListCatalogBooks:
    query: CatalogQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogBookFilter | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> CatalogBookPage:
        normalized_filters = filters or CatalogBookFilter()
        if (normalized_filters.facet_kind is None) != (
            normalized_filters.facet_id is None
        ):
            raise ValueError("facet kind and id must be provided together")
        return self.query.list_books(
            context=context,
            filters=CatalogBookFilter(
                search=normalized_filters.search.strip(),
                facet_kind=normalized_filters.facet_kind,
                facet_id=normalized_filters.facet_id,
                book_ids=normalized_filters.book_ids,
                sort=normalized_filters.sort,
            ),
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )


@dataclass(frozen=True)
class GetCatalogBook:
    query: CatalogQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        book_id: str,
    ) -> CatalogBook | None:
        normalized_id = book_id.strip()
        if not normalized_id:
            return None
        return self.query.get_book(context=context, book_id=normalized_id)


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
