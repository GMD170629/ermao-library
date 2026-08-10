"""SQLAlchemy repository for bounded facet index repair batches."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import LibraryWork
from app.modules.library.domain.facets import CURRENT_FACET_INDEX_VERSION
from app.modules.library.infrastructure.facets import sync_work_facets


class SqlAlchemyFacetIndexRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def pending_work_ids(self, *, limit: int) -> tuple[str, ...]:
        return tuple(
            str(work_id)
            for work_id in self._db.scalars(
                select(LibraryWork.id)
                .where(LibraryWork.facet_index_version < CURRENT_FACET_INDEX_VERSION)
                .order_by(LibraryWork.id.asc())
                .limit(limit)
            )
        )

    def rebuild_work(self, work_id: str) -> None:
        sync_work_facets(self._db, work_id)
