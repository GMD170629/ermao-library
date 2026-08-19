from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.bootstrap.system import write_prepared_system_events
from app.core.config import Settings
from app.models.auth import User
from app.modules.library.application.bookshelf import ListBookshelfItems
from app.modules.library.application.dto import MoveVolumeResult
from app.modules.library.application.filter_options import (
    GetLibraryFilterSchema,
    SearchLibraryFilterOptions,
)
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
)
from app.modules.library.application.work_deletion import (
    DeleteLibraryWorks,
    LibraryDeletionEventStore,
    LibraryWorkDeletionResult,
    PreparedLibraryWorkDeletion,
)
from app.modules.library.application.work_list import WorkListQuery, WorkListResult
from app.modules.library.infrastructure import dashboard as library_dashboard
from app.modules.library.infrastructure import deletion as library_deletion
from app.modules.library.infrastructure import facet_queries as library_facet_queries
from app.modules.library.infrastructure import join_queries as library_join_queries
from app.modules.library.infrastructure import operations as library_operation_store
from app.modules.library.infrastructure import projections as library_projections
from app.modules.library.infrastructure import storage as library_storage
from app.modules.library.infrastructure import works as library_works
from app.modules.library.infrastructure.bookshelf import SqlAlchemyBookshelfItemQueries
from app.modules.library.infrastructure.cover_publication import RemoteCoverPublication
from app.modules.library.infrastructure.deletion import (
    SqlAlchemyLibraryWorkDeletionStore,
)
from app.modules.library.infrastructure.facet_references import (
    SqlAlchemyLibraryFacetReferenceQueries,
)
from app.modules.library.infrastructure.facet_sync import (
    PreparedWorkFacetWrite,
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.modules.library.infrastructure.file_quarantine import (
    LocalLibraryFileQuarantine,
)
from app.modules.library.infrastructure.filter_options import (
    SqlAlchemyLibraryFilterQueries,
)
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.library.infrastructure.request_mutations import (
    SqlAlchemyLibraryRequestMutations,
)
from app.modules.library.infrastructure.request_mutations import (
    load_metadata_apply_job_ids as _load_metadata_apply_job_ids,
)
from app.modules.library.infrastructure.structural_operations import (
    move_volume_to_work as _move_volume_to_work,
)
from app.modules.library.infrastructure.structural_operations import (
    reorder_volume as _reorder_volume,
)
from app.modules.library.infrastructure.volume_commands import SqlAlchemyVolumeStructure
from app.modules.library.infrastructure.work_list import list_works as _list_works
from app.modules.system.public import PreparedSystemEvent

__all__ = [
    "PreparedWorkFacetWrite",
    "bookshelf_items",
    "delete_prepared_library_works",
    "execute_work_facet_write",
    "library_cover_publication",
    "library_dashboard",
    "library_deletion",
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
    "move_volume_to_work",
    "prepare_work_facet_write",
    "reorder_volume",
    "smart_shelf_work_ids",
    "volume_structure_commands",
]


class _LibraryDeletionEventAdapter(LibraryDeletionEventStore):
    def __init__(self, db: Session) -> None:
        self._db = db

    def write(self, events: tuple[PreparedSystemEvent, ...]) -> None:
        write_prepared_system_events(self._db, list(events))


def delete_prepared_library_works(
    db: Session,
    prepared: PreparedLibraryWorkDeletion,
) -> LibraryWorkDeletionResult:
    return DeleteLibraryWorks(
        SqlAlchemyLibraryWorkDeletionStore(db),
        LocalLibraryFileQuarantine(),
        _LibraryDeletionEventAdapter(db),
        db,
    ).execute(prepared)


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


def move_volume_to_work(
    db: Session,
    *,
    source_work_id: str,
    volume_id: str,
    target_work_id: str,
    now: datetime,
) -> MoveVolumeResult:
    return _move_volume_to_work(
        db,
        source_work_id=source_work_id,
        volume_id=volume_id,
        target_work_id=target_work_id,
        now=now,
    )


def reorder_volume(
    db: Session,
    *,
    volume_id: str,
    version_id: str,
    direction: Literal["up", "down"],
    now: datetime,
) -> bool:
    return _reorder_volume(
        db,
        volume_id=volume_id,
        version_id=version_id,
        direction=direction,
        now=now,
    )


def volume_structure_commands(db: Session) -> SqlAlchemyVolumeStructure:
    return SqlAlchemyVolumeStructure(db)
