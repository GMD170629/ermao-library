from __future__ import annotations

from sqlalchemy.orm import Session

from app.bootstrap.system import write_prepared_system_events
from app.core.config import Settings
from app.models.auth import User
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.application.filter_options import (
    GetLibraryFilterSchema,
    SearchLibraryFilterOptions,
)
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
)
from app.modules.library.application.work_list import WorkListQuery, WorkListResult
from app.modules.library.infrastructure import dashboard as library_dashboard
from app.modules.library.infrastructure import facet_queries as library_facet_queries
from app.modules.library.infrastructure import join_queries as library_join_queries
from app.modules.library.infrastructure import operations as library_operation_store
from app.modules.library.infrastructure import projections as library_projections
from app.modules.library.infrastructure import storage as library_storage
from app.modules.library.infrastructure import works as library_works
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries
from app.modules.library.infrastructure.cover_publication import RemoteCoverPublication
from app.modules.library.infrastructure.facet_references import (
    SqlAlchemyLibraryFacetReferenceQueries,
)
from app.modules.library.infrastructure.facet_sync import (
    PreparedWorkFacetWrite,
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.modules.library.infrastructure.filter_options import (
    SqlAlchemyLibraryFilterQueries,
)
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.modules.library.infrastructure.media_kind_sql import (
    volume_effective_media_kind,
)
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.library.infrastructure.request_mutations import (
    SqlAlchemyLibraryRequestMutations,
)
from app.modules.library.infrastructure.request_mutations import (
    load_metadata_apply_job_ids as _load_metadata_apply_job_ids,
)
from app.modules.library.infrastructure.volume_commands import SqlAlchemyVolumeMetadata
from app.modules.library.infrastructure.work_list import list_works as _list_works

__all__ = [
    "PreparedWorkFacetWrite",
    "bookshelf_items",
    "execute_work_facet_write",
    "library_cover_publication",
    "library_dashboard",
    "library_facet_queries",
    "library_facet_references",
    "library_filter_options",
    "library_filter_schema",
    "library_groupings",
    "library_join_queries",
    "library_operation_store",
    "library_projections",
    "library_request_mutations",
    "library_storage",
    "library_works",
    "list_works",
    "load_metadata_apply_job_ids",
    "load_work_facet_projections",
    "prepare_work_facet_write",
    "smart_shelf_work_ids",
    "volume_effective_media_kind",
    "volume_metadata_commands",
]


def bookshelf_items(db: Session) -> ListBookshelfItems:
    return ListBookshelfItems(SqlAlchemyBookshelfItemQueries(db))


def smart_shelf_work_ids(
    db: Session,
    rules: object,
    *,
    user_id: str | None = None,
) -> list[str]:
    query = GetSmartShelfWorkIds(SqlAlchemyLibraryQueries(db))
    return query.execute(
        SmartShelfCriteria.from_external(rules),
        user_id=user_id,
    )


def library_groupings(db: Session) -> ListLibraryGroupings:
    return ListLibraryGroupings(SqlAlchemyLibraryGroupingQueries(db))


def library_facet_references(db: Session) -> SqlAlchemyLibraryFacetReferenceQueries:
    return SqlAlchemyLibraryFacetReferenceQueries(db)


def library_filter_schema(db: Session) -> GetLibraryFilterSchema:
    return GetLibraryFilterSchema(SqlAlchemyLibraryFilterQueries(db))


def library_filter_options(db: Session) -> SearchLibraryFilterOptions:
    return SearchLibraryFilterOptions(SqlAlchemyLibraryFilterQueries(db))


def library_request_mutations(db: Session) -> SqlAlchemyLibraryRequestMutations:
    from app.bootstrap.metadata import persist_metadata_writeback_intents

    return SqlAlchemyLibraryRequestMutations(
        db,
        write_events=write_prepared_system_events,
        write_metadata=persist_metadata_writeback_intents,
    )


def library_cover_publication(settings: Settings) -> RemoteCoverPublication:
    return RemoteCoverPublication(settings.resolved_storage_root)


def load_metadata_apply_job_ids(db: Session, work_id: str) -> tuple[str, ...]:
    return _load_metadata_apply_job_ids(db, work_id)


def list_works(
    db: Session,
    user: User,
    query: WorkListQuery,
) -> WorkListResult:
    return _list_works(db, user, query)


def volume_metadata_commands(db: Session) -> SqlAlchemyVolumeMetadata:
    return SqlAlchemyVolumeMetadata(db)
