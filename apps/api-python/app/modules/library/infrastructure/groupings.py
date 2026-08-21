"""SQLAlchemy queries for browsing visible author and series groupings."""

from __future__ import annotations

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, aliased

from app.core.authorization import AuthorizationContext, book_visibility_predicate
from app.models import LibraryFacet, LibraryBook, LibraryBookFacet
from app.modules.library.application.groupings import (
    LibraryGrouping,
    LibraryGroupingPage,
    LibraryGroupingBook,
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
        filters = [LibraryFacet.kind == kind]
        if kind == "AUTHOR":
            filters.append(func.trim(LibraryFacet.name) != "未知作者")
        if search:
            filters.append(func.lower(LibraryFacet.name).like(f"%{search.casefold()}%"))
        count_link = aliased(LibraryBookFacet)
        count_work = aliased(LibraryBook)
        count_work_visible = select(count_work.id).where(
            count_work.id == count_link.book_id,
            count_work.hidden.is_(False),
            book_visibility_predicate(context, count_work),
        )
        book_count = (
            select(func.count())
            .select_from(count_link)
            .where(
                count_link.facet_id == LibraryFacet.id,
                count_work_visible.exists(),
            )
            .scalar_subquery()
        )
        latest_link = aliased(LibraryBookFacet)
        latest_work = aliased(LibraryBook)
        visible_work_updated_at = (
            select(latest_work.updated_at)
            .where(
                latest_work.id == latest_link.book_id,
                latest_work.hidden.is_(False),
                book_visibility_predicate(context, latest_work),
            )
            .scalar_subquery()
        )
        latest_work_updated_at = (
            select(func.max(visible_work_updated_at))
            .select_from(latest_link)
            .where(
                latest_link.facet_id == LibraryFacet.id,
                visible_work_updated_at.is_not(None),
            )
            .scalar_subquery()
        )
        visible_link = aliased(LibraryBookFacet)
        visible_work = aliased(LibraryBook)
        has_visible_work = exists(
            select(visible_link.book_id).where(
                visible_link.facet_id == LibraryFacet.id,
                select(visible_work.id)
                .where(
                    visible_work.id == visible_link.book_id,
                    visible_work.hidden.is_(False),
                    book_visibility_predicate(context, visible_work),
                )
                .exists(),
            )
        )
        grouped = (
            select(
                LibraryFacet.id.label("facet_id"),
                LibraryFacet.name,
                LibraryFacet.normalized_name,
                LibraryFacet.updated_at.label("facet_updated_at"),
                book_count.label("book_count"),
                latest_work_updated_at.label("latest_work_updated_at"),
            )
            .where(*filters, has_visible_work)
        ).subquery()
        rows = self._db.execute(
            select(grouped, func.count().over().label("total_count"))
            .order_by(
                grouped.c.normalized_name.asc(),
                grouped.c.facet_id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        total = (
            int(rows[0].total_count)
            if rows
            else int(self._db.scalar(select(func.count()).select_from(grouped)) or 0)
        )
        representative_books = self._representative_books(
            context=context,
            facet_ids=tuple(str(row.facet_id) for row in rows),
        )
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
                    representative_books=representative_books.get(
                        str(row.facet_id), ()
                    ),
                )
                for row in rows
            ),
            total=total,
        )

    def _representative_books(
        self,
        *,
        context: AuthorizationContext,
        facet_ids: tuple[str, ...],
    ) -> dict[str, tuple[LibraryGroupingBook, ...]]:
        if not facet_ids:
            return {}
        ranked = (
            select(
                LibraryBookFacet.facet_id.label("facet_id"),
                LibraryBook.id.label("book_id"),
                LibraryBook.title,
                LibraryBook.author,
                LibraryBook.cover_path,
                LibraryBook.updated_at,
                func.row_number()
                .over(
                    partition_by=LibraryBookFacet.facet_id,
                    order_by=(LibraryBook.updated_at.desc(), LibraryBook.id.asc()),
                )
                .label("representative_rank"),
            )
            .join(LibraryBook, LibraryBook.id == LibraryBookFacet.book_id)
            .where(
                LibraryBookFacet.facet_id.in_(facet_ids),
                LibraryBook.hidden.is_(False),
                book_visibility_predicate(context),
            )
            .subquery()
        )
        rows = self._db.execute(
            select(ranked)
            .where(ranked.c.representative_rank <= 3)
            .order_by(ranked.c.facet_id.asc(), ranked.c.representative_rank.asc())
        ).all()
        grouped: dict[str, list[LibraryGroupingBook]] = {}
        for row in rows:
            grouped.setdefault(str(row.facet_id), []).append(
                LibraryGroupingBook(
                    id=str(row.book_id),
                    title=str(row.title),
                    author=str(row.author or ""),
                    cover_path=(str(row.cover_path) if row.cover_path else None),
                    updated_at=row.updated_at,
                )
            )
        return {facet_id: tuple(books) for facet_id, books in grouped.items()}
