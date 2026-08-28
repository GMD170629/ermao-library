"""Composition root for Library application ports."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.bootstrap.publications import PublicationRuntime, ensure_publication_navigation
from app.core.config import Settings
from app.models import LibraryBook, MetadataLookupTask
from app.models.auth import User
from app.modules.library.application.asset_commands import DeleteResourceAsset
from app.modules.library.application.book_commands import UpdateBook
from app.modules.library.application.book_contents import BrowseBookContents
from app.modules.library.application.book_list import BookListQuery, BookListResult
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.application.bulk_operations import (
    ExecuteBulkFindReplace,
    ExecuteBulkMetadata,
    ExecuteBulkReadingStatus,
    ExecuteBulkShelfMembership,
    PreviewBulkFindReplace,
)
from app.modules.library.application.dashboard import DashboardQueries
from app.modules.library.application.facet_sync import (
    prepare_book_facet,
)
from app.modules.library.application.filter_options import (
    GetLibraryFilterSchema,
    SearchLibraryFilterOptions,
)
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.application.management_commands import (
    DeleteLibraryFacet,
    MergeLibraryFacets,
    RenameLibraryFacet,
    UndoLibraryOperation,
)
from app.modules.library.application.queries import (
    SmartShelfCriteria,
)
from app.modules.library.application.recognized_metadata import (
    ApplyRecognizedCover,
    ApplyRecognizedMetadata,
)
from app.modules.library.application.resource_details import (
    ListResourceDetails,
    ResourceDetailAccessScope,
    ResourceNavigationPreparer,
)
from app.modules.library.application.source_node_commands import (
    UpdateSourceNodeMetadata,
    UpdateSourceNodePresentation,
)
from app.modules.library.application.source_node_metadata_recognition import (
    RecognizeSourceNodeMetadata,
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
from app.modules.library.infrastructure.book_contents import (
    SqlAlchemyBookContentsQueries,
)
from app.modules.library.infrastructure.book_covers import SqlAlchemyBookCoverQueries
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries
from app.modules.library.infrastructure.bulk_operations import (
    SqlAlchemyBulkBookOperations,
)
from app.modules.library.infrastructure.catalog import SqlAlchemyCatalogQueries
from app.modules.library.infrastructure.cover_publication import RemoteCoverPublication
from app.modules.library.infrastructure.facet_management import (
    SqlAlchemyLibraryFacetManagement,
)
from app.modules.library.infrastructure.facet_sync import (
    PreparedBookFacetWrite,
    execute_book_facet_write,
    load_book_facet_projections,
    prepare_book_facet_write,
)
from app.modules.library.infrastructure.filter_options import (
    SqlAlchemyLibraryFilterQueries,
)
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.modules.library.infrastructure.legacy_views import (
    book_view,
    bookshelf_book_list_view,
    bookshelf_item_view,
    bookshelf_item_views,
    list_resource_views,
    management_book_list_view,
    preferred_book_cover_path,
    resource_view,
)
from app.modules.library.infrastructure.operation_management import (
    SqlAlchemyLibraryOperationManagement,
)
from app.modules.library.infrastructure.recognized_metadata import (
    FilesystemRecognizedCoverPublication,
    SafeRemoteCoverDownloader,
    SqlAlchemyRecognizedMetadata,
)
from app.modules.library.infrastructure.resource_commands import (
    SqlAlchemyResourceMetadata,
)
from app.modules.library.infrastructure.resource_details import (
    SqlAlchemyResourceDetailQueries,
)
from app.modules.library.infrastructure.source_node_commands import (
    SqlAlchemySourceNodeMetadata,
)
from app.modules.library.infrastructure.source_node_cover import (
    FilesystemSourceNodeCoverPublication,
)
from app.modules.library.infrastructure.source_node_metadata_recognition import (
    ProviderSourceNodeMetadataRecognition,
)
from app.modules.publications.public import (
    PublicationAccessScope,
    PublicationCorruptError,
    PublicationNotFoundError,
    PublicationResourceTooLargeError,
    PublicationUnsupportedError,
)


class _PublicationResourceNavigationPreparer(ResourceNavigationPreparer):
    def __init__(
        self,
        factory: sessionmaker[Session],
        runtime: PublicationRuntime,
    ) -> None:
        self._factory = factory
        self._runtime = runtime

    def prepare(self, *, resource_id: str, context: ResourceDetailAccessScope) -> None:
        access = PublicationAccessScope(
            is_admin=context.is_admin,
            can_view_manual_imports=context.can_view_manual_imports,
            library_ids=tuple(context.library_ids),
        )
        try:
            ensure_publication_navigation(self._factory, self._runtime).execute(
                resource_id=resource_id,
                access_scope=access,
            )
        except (
            PublicationCorruptError,
            PublicationNotFoundError,
            PublicationUnsupportedError,
            PublicationResourceTooLargeError,
        ):
            return


def bookshelf_items(db: Session) -> ListBookshelfItems:
    return ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db))


def library_catalog(db: Session) -> SqlAlchemyCatalogQueries:
    return SqlAlchemyCatalogQueries(db)


def effective_book_cover_paths(
    db: Session, book_ids: tuple[str, ...]
) -> dict[str, str]:
    return dict(SqlAlchemyBookCoverQueries(db).preferred_paths(book_ids))


def bulk_metadata(db: Session) -> ExecuteBulkMetadata:
    return ExecuteBulkMetadata(SqlAlchemyBulkBookOperations(db), db)


def bulk_find_replace_preview(db: Session) -> PreviewBulkFindReplace:
    return PreviewBulkFindReplace(SqlAlchemyBulkBookOperations(db))


def bulk_find_replace(db: Session) -> ExecuteBulkFindReplace:
    return ExecuteBulkFindReplace(SqlAlchemyBulkBookOperations(db), db)


def bulk_shelf_membership(db: Session) -> ExecuteBulkShelfMembership:
    return ExecuteBulkShelfMembership(SqlAlchemyBulkBookOperations(db), db)


def bulk_reading_status(db: Session) -> ExecuteBulkReadingStatus:
    return ExecuteBulkReadingStatus(SqlAlchemyBulkBookOperations(db), db)


def merge_library_facets(db: Session) -> MergeLibraryFacets:
    return MergeLibraryFacets(SqlAlchemyLibraryFacetManagement(db), db)


def rename_library_facet(db: Session) -> RenameLibraryFacet:
    return RenameLibraryFacet(SqlAlchemyLibraryFacetManagement(db), db)


def delete_library_facet(db: Session) -> DeleteLibraryFacet:
    return DeleteLibraryFacet(SqlAlchemyLibraryFacetManagement(db), db)


def undo_library_operation(db: Session) -> UndoLibraryOperation:
    return UndoLibraryOperation(SqlAlchemyLibraryOperationManagement(db), db)


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


def library_groupings(db: Session) -> ListLibraryGroupings:
    return ListLibraryGroupings(SqlAlchemyLibraryGroupingQueries(db))


def dashboard_queries(db: Session) -> DashboardQueries:
    return DashboardQueries(
        activity=library_dashboard.SqlAlchemyDashboardActivityQueries(db),
        bookshelf=SqlAlchemyBookshelfItemQueries(db),
    )


def library_cover_publication(settings: Settings) -> RemoteCoverPublication:
    return RemoteCoverPublication(settings.resolved_storage_root)


def get_book(db: Session, book_id: str) -> dict[str, object] | None:
    return library_books.get_book(db, book_id)


def update_book(db: Session) -> UpdateBook:
    return UpdateBook(SqlAlchemyBookMutation(db), db)


def browse_book_contents(db: Session) -> BrowseBookContents:
    return BrowseBookContents(SqlAlchemyBookContentsQueries(db))


def resource_details(
    db: Session,
    *,
    user_id: str,
    session_factory: sessionmaker[Session],
    settings: Settings,
    runtime: PublicationRuntime,
) -> ListResourceDetails:
    return ListResourceDetails(
        SqlAlchemyResourceDetailQueries(db, user_id),
        _PublicationResourceNavigationPreparer(session_factory, runtime),
    )


def update_source_node_metadata(db: Session) -> UpdateSourceNodeMetadata:
    return UpdateSourceNodeMetadata(SqlAlchemySourceNodeMetadata(db), db)


def update_source_node_presentation(
    db: Session, settings: Settings
) -> UpdateSourceNodePresentation:
    return UpdateSourceNodePresentation(
        SqlAlchemySourceNodeMetadata(db),
        FilesystemSourceNodeCoverPublication(settings.resolved_storage_root),
        db,
    )


def recognize_source_node_metadata(db: Session) -> RecognizeSourceNodeMetadata:
    return RecognizeSourceNodeMetadata(ProviderSourceNodeMetadataRecognition(db))


def apply_recognized_metadata(
    db: Session,
    settings: Settings,
) -> ApplyRecognizedMetadata:
    adapter = SqlAlchemyRecognizedMetadata(db)
    covers = ApplyRecognizedCover(
        adapter,
        SafeRemoteCoverDownloader(),
        FilesystemRecognizedCoverPublication(settings.resolved_storage_root),
        db,
    )
    return ApplyRecognizedMetadata(adapter, db, covers)


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
    "apply_recognized_metadata",
    "book_view",
    "bookshelf_book_list_view",
    "bookshelf_item_view",
    "bookshelf_item_views",
    "bookshelf_items",
    "browse_book_contents",
    "bulk_find_replace",
    "bulk_find_replace_preview",
    "bulk_metadata",
    "bulk_reading_status",
    "bulk_shelf_membership",
    "delete_library_facet",
    "delete_resource_asset",
    "effective_book_cover_paths",
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
    "list_resource_views",
    "load_book_facet_projections",
    "load_metadata_apply_job_ids",
    "management_book_list_view",
    "merge_library_facets",
    "preferred_book_cover_path",
    "prepare_book_facet",
    "prepare_book_facet_write",
    "recognize_source_node_metadata",
    "rename_library_facet",
    "resource_details",
    "resource_metadata",
    "resource_view",
    "smart_shelf_book_ids",
    "update_book",
    "update_source_node_metadata",
    "update_source_node_presentation",
]
