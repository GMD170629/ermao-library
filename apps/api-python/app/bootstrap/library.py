from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.models.auth import User
from app.modules.library.application.dto import MoveVolumeResult
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
)
from app.modules.library.application.work_list import WorkListQuery, WorkListResult
from app.modules.library.application.work_merge import MergeMetadataWritebackPort
from app.modules.library.infrastructure import dashboard as library_dashboard
from app.modules.library.infrastructure import deletion as library_deletion
from app.modules.library.infrastructure import facet_queries as library_facet_queries
from app.modules.library.infrastructure import join_queries as library_join_queries
from app.modules.library.infrastructure import operations as library_operation_store
from app.modules.library.infrastructure import projections as library_projections
from app.modules.library.infrastructure import storage as library_storage
from app.modules.library.infrastructure import works as library_works
from app.modules.library.infrastructure.groupings import (
    SqlAlchemyLibraryGroupingQueries,
)
from app.modules.library.infrastructure.queries import SqlAlchemyLibraryQueries
from app.modules.library.infrastructure.structural_operations import (
    move_volume_to_work as _move_volume_to_work,
)
from app.modules.library.infrastructure.structural_operations import (
    reorder_volume as _reorder_volume,
)
from app.modules.library.infrastructure.volume_commands import SqlAlchemyVolumeStructure
from app.modules.library.infrastructure.work_list import list_works as _list_works
from app.modules.library.infrastructure.work_merge import SqlAlchemyWorkMergeGateway
from app.modules.metadata.infrastructure.writeback_queue import (
    enqueue_writeback,
    operation_view,
    write_metadata_to_files_enabled,
)

__all__ = [
    "library_dashboard",
    "library_deletion",
    "library_facet_queries",
    "library_groupings",
    "library_join_queries",
    "library_operation_store",
    "library_projections",
    "library_storage",
    "library_works",
    "list_works",
    "move_volume_to_work",
    "reorder_volume",
    "smart_shelf_work_ids",
    "volume_structure_commands",
    "work_merge_gateway",
]


class _MetadataWritebackAdapter(MergeMetadataWritebackPort):
    def __init__(self, db: Session) -> None:
        self._db = db

    def enabled(self) -> bool:
        return write_metadata_to_files_enabled(self._db)

    def enqueue(
        self, *, work_id: str, media_version_id: str
    ) -> dict[str, object] | None:
        operation_id = enqueue_writeback(
            self._db,
            work_id=work_id,
            media_version_id=media_version_id,
            source="MANUAL",
        )
        return operation_view(self._db, operation_id)


def work_merge_gateway(db: Session) -> SqlAlchemyWorkMergeGateway:
    return SqlAlchemyWorkMergeGateway(db, _MetadataWritebackAdapter(db))


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
    media_version_id: str,
    direction: Literal["up", "down"],
    now: datetime,
) -> bool:
    return _reorder_volume(
        db,
        volume_id=volume_id,
        media_version_id=media_version_id,
        direction=direction,
        now=now,
    )


def volume_structure_commands(db: Session) -> SqlAlchemyVolumeStructure:
    from app.bootstrap.imports import stage_import_task_with_work_item

    return SqlAlchemyVolumeStructure(db, stage_import_task_with_work_item)
