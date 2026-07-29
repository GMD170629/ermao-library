"""SQLAlchemy queries for browsing visible author and series groupings."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, work_visibility_predicate
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.groupings import (
    LibraryGrouping,
    LibraryGroupingPage,
)


class SqlAlchemyLibraryGroupingQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_groupings(
        self,
        *,
        kind: str,
        context: AuthorizationContext,
        search: str,
        page: int,
        page_size: int,
    ) -> LibraryGroupingPage:
        filters = [
            LibraryFacet.kind == kind,
            LibraryWork.hidden.is_(False),
            work_visibility_predicate(context),
        ]
        if kind == "AUTHOR":
            filters.append(func.trim(LibraryFacet.name) != "未知作者")
        if search:
            filters.append(func.lower(LibraryFacet.name).like(f"%{search.casefold()}%"))
        grouped = (
            select(
                LibraryFacet.id.label("facet_id"),
                LibraryFacet.name,
                LibraryFacet.normalized_name,
                LibraryFacet.updated_at.label("facet_updated_at"),
                func.count(func.distinct(LibraryWork.id)).label("book_count"),
                func.max(LibraryWork.updated_at).label("latest_work_updated_at"),
            )
            .join(
                LibraryWorkFacet,
                LibraryWorkFacet.facet_id == LibraryFacet.id,
            )
            .join(
                LibraryWork,
                LibraryWork.id == LibraryWorkFacet.work_id,
            )
            .where(*filters)
            .group_by(
                LibraryFacet.id,
                LibraryFacet.name,
                LibraryFacet.normalized_name,
                LibraryFacet.updated_at,
            )
        ).subquery()
        total = int(self._db.scalar(select(func.count()).select_from(grouped)) or 0)
        rows = self._db.execute(
            select(grouped)
            .order_by(
                grouped.c.normalized_name.asc(),
                grouped.c.facet_id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return LibraryGroupingPage(
            groups=tuple(
                LibraryGrouping(
                    id=str(row.facet_id),
                    name=str(row.name),
                    normalized_name=str(row.normalized_name),
                    book_count=int(row.book_count),
                    updated_at=max(
                        row.facet_updated_at,
                        row.latest_work_updated_at,
                    ),
                )
                for row in rows
            ),
            total=total,
        )
