"""ORM helpers for visible library facet and filter option queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    book_visibility_predicate,
    resource_visibility_predicate,
)
from app.models import (
    LibraryBook,
    LibraryBookFacet,
    LibraryBookMetadata,
    LibraryFacet,
    LibraryReadableResource,
)
from app.modules.library.infrastructure.books import entity_record


def list_visible_books(
    db: Session, context: AuthorizationContext
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(LibraryBook, LibraryBookMetadata)
        .select_from(LibraryBook)
        .outerjoin(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(
            LibraryBook.visibility_state == "VISIBLE",
            book_visibility_predicate(context),
        )
    ).all()
    return [
        {
            **entity_record(book),
            "title": metadata.title if metadata else "",
            "author": metadata.author if metadata else None,
            "seriesName": metadata.series_name if metadata else None,
        }
        for book, metadata in rows
    ]


def media_kind_counts(
    db: Session, context: AuthorizationContext
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryReadableResource.media_kind.label("value"),
            func.count(func.distinct(LibraryReadableResource.book_id)).label("count"),
        )
        .select_from(LibraryReadableResource)
        .where(resource_visibility_predicate(context))
        .group_by(LibraryReadableResource.media_kind)
    ).all()
    return [
        {"value": row.value, "count": int(row._mapping["count"] or 0)} for row in rows
    ]


def visible_categories(
    db: Session,
    context: AuthorizationContext,
    kind: str,
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryFacet,
            func.count(func.distinct(LibraryBook.id)).label("bookCount"),
        )
        .join(LibraryBookFacet, LibraryBookFacet.facet_id == LibraryFacet.id)
        .join(LibraryBook, LibraryBook.id == LibraryBookFacet.book_id)
        .where(
            LibraryFacet.kind == kind.upper(),
            LibraryBook.visibility_state == "VISIBLE",
            book_visibility_predicate(context),
        )
        .group_by(LibraryFacet.id)
        .order_by(
            func.count(func.distinct(LibraryBook.id)).desc(),
            LibraryFacet.name.asc(),
        )
    ).all()
    result: list[dict[str, Any]] = []
    for facet, book_count in rows:
        row = entity_record(facet)
        row["bookCount"] = int(book_count or 0)
        result.append(row)
    return result


def list_series_groups(
    db: Session,
    context: AuthorizationContext,
    *,
    visibility: str,
    limit: int,
    min_books: int,
) -> tuple[list[dict[str, Any]], int]:
    filters = [
        LibraryBookMetadata.series_name.is_not(None),
        func.trim(LibraryBookMetadata.series_name) != "",
        LibraryBook.visibility_state == "VISIBLE",
        book_visibility_predicate(context),
    ]
    if visibility == "ignored":
        return [], 0
    name = func.trim(LibraryBookMetadata.series_name).label("name")
    grouped = (
        select(
            name,
            func.count().label("bookCount"),
            func.max(LibraryBook.updated_at).label("latestUpdatedAt"),
        )
        .select_from(LibraryBook)
        .join(LibraryBookMetadata, LibraryBookMetadata.book_id == LibraryBook.id)
        .where(*filters)
        .group_by(name)
        .having(func.count() >= min_books)
        .order_by(func.max(LibraryBook.updated_at).desc(), name.asc())
    )
    total = int(db.scalar(select(func.count()).select_from(grouped.subquery())) or 0)
    rows = db.execute(grouped.limit(limit)).all()
    return [
        {
            "name": row.name,
            "bookCount": int(row.bookCount or 0),
            "latestUpdatedAt": row.latestUpdatedAt,
        }
        for row in rows
    ], total
