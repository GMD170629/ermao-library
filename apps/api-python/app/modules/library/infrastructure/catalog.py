"""SQLAlchemy catalog queries for visible Books and ReadableResources."""

from __future__ import annotations

import json
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, book_visibility_predicate
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
    LibraryResourceAssetMetadata,
    LibrarySourceNode,
)
from app.modules.library.application.catalog import (
    CatalogAsset,
    CatalogBook,
    CatalogBookFacet,
    CatalogBookFilter,
    CatalogBookPage,
    CatalogFacet,
    CatalogFacetKind,
    CatalogFacetPage,
    CatalogQueryPort,
    CatalogResource,
)


class SqlAlchemyCatalogQueries(CatalogQueryPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def _book_predicates(self, context: AuthorizationContext):
        return [book_visibility_predicate(context)]

    def list_books(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogBookFilter,
        page: int,
        page_size: int,
    ) -> CatalogBookPage:
        predicates = self._book_predicates(context)
        if filters.book_ids:
            predicates.append(self._book_id_column().in_(filters.book_ids))
        if filters.search:
            query = f"%{filters.search}%"
            predicates.append(
                or_(
                    LibraryBookMetadata.title.ilike(query),
                    LibraryBookMetadata.author.ilike(query),
                    LibraryBookMetadata.series_name.ilike(query),
                )
            )
        if filters.facet_kind and filters.facet_id:
            predicates.append(
                self._book_id_column().in_(
                    select(LibraryBookFacet.book_id)
                    .join(LibraryFacet, LibraryFacet.id == LibraryBookFacet.facet_id)
                    .where(
                        LibraryFacet.kind == filters.facet_kind,
                        LibraryFacet.id == filters.facet_id,
                    )
                )
            )
        base = (
            select(LibraryBook, LibraryBookMetadata)
            .outerjoin(
                LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id
            )
            .where(*predicates)
        )
        total = int(
            self._db.scalar(select(func.count()).select_from(base.subquery())) or 0
        )
        order: tuple[Any, ...] = (
            LibraryBookMetadata.title.asc(),
            LibraryBook.id.asc(),
        )
        if filters.sort == "recent":
            order = (LibraryBook.updated_at.desc(), LibraryBook.id.asc())
        rows = self._db.execute(
            base.order_by(*order).offset((page - 1) * page_size).limit(page_size)
        ).all()
        books = tuple(
            self._assemble_book(book, metadata, context) for book, metadata in rows
        )
        return CatalogBookPage(
            books=books,
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max((book.updated_at for book in books), default=None),
        )

    def get_book(
        self, *, context: AuthorizationContext, book_id: str
    ) -> CatalogBook | None:
        page = self.list_books(
            context=context,
            filters=CatalogBookFilter(book_ids=(book_id,)),
            page=1,
            page_size=1,
        )
        return page.books[0] if page.books else None

    def list_facets(
        self,
        *,
        context: AuthorizationContext,
        kind: CatalogFacetKind,
        search: str,
        page: int,
        page_size: int,
    ) -> CatalogFacetPage:
        predicates = [LibraryFacet.kind == kind]
        if search:
            predicates.append(LibraryFacet.name.ilike(f"%{search}%"))
        visible_book_ids = select(LibraryBook.id).where(
            book_visibility_predicate(context)
        )
        base = (
            select(LibraryFacet, func.count(LibraryBook.id))
            .outerjoin(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
            .outerjoin(
                LibraryBook,
                (LibraryBook.id == LibraryBookFacet.book_id)
                & LibraryBook.id.in_(visible_book_ids),
            )
            .where(*predicates)
            .group_by(LibraryFacet.id)
        )
        total = int(
            self._db.scalar(
                select(func.count()).select_from(LibraryFacet).where(*predicates)
            )
            or 0
        )
        rows = self._db.execute(
            base.order_by(LibraryFacet.name.asc(), LibraryFacet.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        facets = tuple(
            CatalogFacet(
                id=facet.id,
                kind=cast(CatalogFacetKind, facet.kind),
                name=facet.name,
                normalized_name=facet.normalized_name,
                aliases=tuple(
                    str(alias)
                    for alias in json.loads(facet.aliases or "[]")
                    if isinstance(alias, str)
                ),
                book_count=int(count or 0),
                updated_at=facet.updated_at,
            )
            for facet, count in rows
        )
        return CatalogFacetPage(
            facets=facets,
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max((facet.updated_at for facet in facets), default=None),
        )

    @staticmethod
    def _book_id_column():
        return cast(Any, LibraryBook.id)

    def _assemble_book(
        self,
        book,
        metadata: LibraryBookMetadata | None,
        context: AuthorizationContext,
    ) -> CatalogBook:
        facets = tuple(
            CatalogBookFacet(
                id=facet.id,
                kind=cast(CatalogFacetKind, facet.kind),
                name=facet.name,
            )
            for facet in self._db.scalars(
                select(LibraryFacet)
                .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
                .where(LibraryBookFacet.book_id == book.id)
                .order_by(LibraryFacet.kind, LibraryFacet.name, LibraryFacet.id)
            ).all()
        )
        resources = tuple(
            self._resource(resource, resource_metadata)
            for resource, resource_metadata in self._db.execute(
                select(LibraryReadableResource, LibraryReadableResourceMetadata)
                .outerjoin(
                    LibraryReadableResourceMetadata,
                    LibraryReadableResourceMetadata.resource_id
                    == LibraryReadableResource.id,
                )
                .where(
                    LibraryReadableResource.book_id == book.id,
                    LibraryReadableResource.enablement_state == "ENABLED",
                    LibraryReadableResource.import_state == "READY",
                )
                .order_by(LibraryReadableResource.id)
            ).all()
        )
        return CatalogBook(
            id=book.id,
            title=metadata.title if metadata else "",
            author=metadata.author if metadata else None,
            description=metadata.description if metadata else None,
            series_name=metadata.series_name if metadata else None,
            series_index=metadata.series_index if metadata else None,
            has_cover=(
                bool(metadata and metadata.cover_path)
                or any(resource.has_cover for resource in resources)
            ),
            facets=facets,
            resources=resources,
            created_at=book.created_at,
            updated_at=book.updated_at,
        )

    def _resource(
        self,
        resource: LibraryReadableResource,
        metadata: LibraryReadableResourceMetadata | None,
    ) -> CatalogResource:
        asset_row = self._db.execute(
            select(
                LibraryResourceAsset, LibraryResourceAssetMetadata, LibrarySourceNode
            )
            .outerjoin(
                LibraryResourceAssetMetadata,
                LibraryResourceAssetMetadata.asset_id == LibraryResourceAsset.id,
            )
            .join(
                LibrarySourceNode,
                LibrarySourceNode.id == LibraryResourceAsset.source_node_id,
            )
            .where(
                LibraryResourceAsset.resource_id == resource.id,
                LibraryResourceAsset.import_state == "READY",
                LibrarySourceNode.physical_kind == "REGULAR_FILE",
            )
            .order_by(LibraryResourceAsset.sequence_index, LibraryResourceAsset.id)
        ).first()
        if asset_row is None:
            asset = CatalogAsset(
                id="",
                mime_type="application/octet-stream",
                size_bytes=0,
                updated_at=resource.updated_at,
            )
        else:
            asset_row_entity, asset_metadata, source = asset_row
            asset = CatalogAsset(
                id=asset_row_entity.id,
                mime_type=asset_metadata.mime_type
                if asset_metadata and asset_metadata.mime_type
                else "application/octet-stream",
                size_bytes=int(source.observed_size_bytes or 0),
                updated_at=source.updated_at,
            )
        return CatalogResource(
            id=resource.id,
            title=metadata.title if metadata else "",
            format=resource.format,
            resource_index=metadata.resource_index if metadata else None,
            sort_order=int(metadata.resource_index or 0)
            if metadata and metadata.resource_index is not None
            else 0,
            description=metadata.description if metadata else None,
            language=metadata.language if metadata else None,
            publisher=metadata.publisher if metadata else None,
            published_at=metadata.published_at if metadata else None,
            identifier=metadata.identifier if metadata else None,
            isbn=metadata.isbn if metadata else None,
            page_count=metadata.page_count if metadata else None,
            has_cover=bool(metadata and metadata.cover_path),
            asset=asset,
            updated_at=resource.updated_at,
        )
