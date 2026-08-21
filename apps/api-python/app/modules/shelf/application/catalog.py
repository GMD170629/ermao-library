"""Read-only application contracts for publishing personal static shelves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.core.authorization import AuthorizationContext


@dataclass(frozen=True)
class CatalogShelf:
    id: str
    name: str
    description: str | None
    updated_at: datetime


@dataclass(frozen=True)
class CatalogShelfPage:
    shelves: tuple[CatalogShelf, ...]
    total: int
    page: int
    page_size: int
    updated_at: datetime | None


@dataclass(frozen=True)
class CatalogShelfBookPage:
    shelf: CatalogShelf
    book_ids: tuple[str, ...]
    total: int
    page: int
    page_size: int
    updated_at: datetime | None


class CatalogShelfQueryPort(Protocol):
    def list_shelves(
        self,
        *,
        context: AuthorizationContext,
        page: int,
        page_size: int,
    ) -> CatalogShelfPage: ...

    def list_shelf_book_ids(
        self,
        *,
        context: AuthorizationContext,
        shelf_id: str,
        page: int,
        page_size: int,
    ) -> CatalogShelfBookPage | None: ...


@dataclass(frozen=True)
class ListCatalogShelves:
    query: CatalogShelfQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        page: int = 1,
        page_size: int = 50,
    ) -> CatalogShelfPage:
        return self.query.list_shelves(
            context=context,
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )


@dataclass(frozen=True)
class ListCatalogShelfBookIds:
    query: CatalogShelfQueryPort

    def execute(
        self,
        *,
        context: AuthorizationContext,
        shelf_id: str,
        page: int = 1,
        page_size: int = 100,
    ) -> CatalogShelfBookPage | None:
        normalized_id = shelf_id.strip()
        if not normalized_id:
            return None
        return self.query.list_shelf_book_ids(
            context=context,
            shelf_id=normalized_id,
            page=max(1, page),
            page_size=min(100, max(1, page_size)),
        )
