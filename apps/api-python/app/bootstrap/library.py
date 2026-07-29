from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.auth import User
from app.modules.library.application.dto import MoveVolumeResult
from app.modules.library.application.groupings import ListLibraryGroupings
from app.modules.library.application.queries import (
    GetSmartShelfWorkIds,
    SmartShelfCriteria,
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
from app.modules.library.infrastructure.work_list import list_works as _list_works


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
    source_format: str,
    now: datetime,
) -> MoveVolumeResult:
    return _move_volume_to_work(
        db,
        source_work_id=source_work_id,
        volume_id=volume_id,
        target_work_id=target_work_id,
        source_format=source_format,
        now=now,
    )


def reorder_volume(
    db: Session,
    *,
    volume_id: str,
    edition_id: str,
    direction: str,
    now: datetime,
) -> bool:
    return _reorder_volume(
        db,
        volume_id=volume_id,
        edition_id=edition_id,
        direction=direction,
        now=now,
    )
