"""Composition root for Library application ports."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import LibraryBook, MetadataLookupTask
from app.models.auth import User
from app.modules.library.application.asset_commands import DeleteResourceAsset
from app.modules.library.application.book_commands import UpdateBook
from app.modules.library.application.book_list import BookListQuery, BookListResult
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.application.facet_sync import (
    prepare_book_facet,
)
from app.modules.library.application.filter_options import (
    GetLibraryFilterSchema,
    SearchLibraryFilterOptions,
)
from app.modules.library.application.queries import (
    SmartShelfCriteria,
)
from app.modules.library.infrastructure import book_list as library_book_list
from app.modules.library.infrastructure import books as library_books
from app.modules.library.infrastructure import dashboard as library_dashboard
from app.modules.library.infrastructure import facet_queries as library_facet_queries
from app.modules.library.infrastructure import operations as library_operation_store
from app.modules.library.infrastructure import projections as library_projections
from app.modules.library.infrastructure import (
    request_mutations as library_request_mutations,
)
from app.modules.library.infrastructure import storage as library_storage
from app.modules.library.infrastructure.asset_commands import (
    SqlAlchemyResourceAssetMutation,
)
from app.modules.library.infrastructure.book_commands import SqlAlchemyBookMutation
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries
from app.modules.library.infrastructure.cover_publication import RemoteCoverPublication
from app.modules.library.infrastructure.facet_sync import (
    PreparedBookFacetWrite,
    execute_book_facet_write,
    load_book_facet_projections,
    prepare_book_facet_write,
)
from app.modules.library.infrastructure.filter_options import (
    SqlAlchemyLibraryFilterQueries,
)
from app.modules.library.infrastructure.resource_commands import (
    SqlAlchemyResourceMetadata,
)


def bookshelf_items(db: Session) -> ListBookshelfItems:
    return ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db))


def library_catalog(db: Session) -> SqlAlchemyCatalogQueries:
    return SqlAlchemyCatalogQueries(db)


def smart_shelf_book_ids(
    db: Session,
    rules: object,
    *,
    user_id: str | None = None,
) -> list[str]:
    criteria = SmartShelfCriteria.from_external(rules)
    statement = select(LibraryBook.id)
    if criteria.search:
        from app.models import LibraryBookMetadata

        term = f"%{criteria.search}%"
        statement = statement.join(
            LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id
        ).where(
            LibraryBookMetadata.title.ilike(term)
            | LibraryBookMetadata.author.ilike(term)
        )
    if user_id:
        from app.models import UserLibraryAccess

        library_ids = select(UserLibraryAccess.library_id).where(
            UserLibraryAccess.user_id == user_id
        )
        statement = statement.where(LibraryBook.library_id.in_(library_ids))
    return [
        str(book_id) for book_id in db.scalars(statement.order_by(LibraryBook.id)).all()
    ]


def library_filter_schema(db: Session) -> GetLibraryFilterSchema:
    return GetLibraryFilterSchema(SqlAlchemyLibraryFilterQueries(db))


def library_filter_options(db: Session) -> SearchLibraryFilterOptions:
    return SearchLibraryFilterOptions(SqlAlchemyLibraryFilterQueries(db))


def library_cover_publication(settings: Settings) -> RemoteCoverPublication:
    return RemoteCoverPublication(settings.resolved_storage_root)


def get_book(db: Session, book_id: str) -> dict[str, object] | None:
    return library_books.get_book(db, book_id)


def update_book(db: Session) -> UpdateBook:
    return UpdateBook(SqlAlchemyBookMutation(db), db)


def delete_resource_asset(db: Session) -> DeleteResourceAsset:
    return DeleteResourceAsset(SqlAlchemyResourceAssetMutation(db), db)


def resource_metadata(db: Session) -> SqlAlchemyResourceMetadata:
    return SqlAlchemyResourceMetadata(db)


def load_metadata_apply_job_ids(db: Session, book_id: str) -> tuple[str, ...]:
    return tuple(
        str(task.id)
        for task in db.scalars(
            select(MetadataLookupTask)
            .where(MetadataLookupTask.book_id == book_id)
            .order_by(MetadataLookupTask.created_at.desc())
        ).all()
    )


def list_books(db: Session, user: User, query: BookListQuery) -> BookListResult:
    return library_book_list.list_books(db, user, query)


__all__ = [
    "PreparedBookFacetWrite",
    "bookshelf_items",
    "delete_resource_asset",
    "execute_book_facet_write",
    "get_book",
    "library_books",
    "library_catalog",
    "library_cover_publication",
    "library_dashboard",
    "library_facet_queries",
    "library_filter_options",
    "library_filter_schema",
    "library_operation_store",
    "library_projections",
    "library_request_mutations",
    "library_storage",
    "list_books",
    "load_book_facet_projections",
    "load_metadata_apply_job_ids",
    "prepare_book_facet",
    "prepare_book_facet_write",
    "resource_metadata",
    "smart_shelf_book_ids",
    "update_book",
]
