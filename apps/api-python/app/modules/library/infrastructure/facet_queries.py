"""ORM helpers for visible library facet / filter option queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.library import (
    LibraryFacet,
    LibraryMediaVersion,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def list_visible_works(
    db: Session, context: AuthorizationContext
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(LibraryWork).where(
            func.coalesce(LibraryWork.hidden, False).is_(False),
            work_visibility_predicate(context),
        )
    ).all()
    return [entity_as_legacy_dict(row) for row in rows]


def media_kind_counts(
    db: Session, context: AuthorizationContext
) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryMediaVersion.media_kind.label("value"),
            func.count(func.distinct(LibraryMediaVersion.work_id)).label("count"),
        )
        .join(LibraryVolume, LibraryVolume.version_id == LibraryVersion.id)
        .where(
            LibraryVolume.hidden.is_(False),
            volume_visibility_predicate(context),
        )
        .group_by(LibraryMediaVersion.media_kind)
    ).all()
    return [{"value": row.value, "count": int(row.count or 0)} for row in rows]


def visible_categories(
    db: Session,
    context: AuthorizationContext,
    kind: str,
) -> list[dict[str, Any]]:
    normalized = kind.upper()
    rows = db.execute(
        select(
            LibraryFacet,
            func.count(func.distinct(LibraryWork.id)).label("bookCount"),
        )
        .join(LibraryWorkFacet, LibraryWorkFacet.facet_id == LibraryFacet.id)
        .join(LibraryWork, LibraryWork.id == LibraryWorkFacet.work_id)
        .where(
            LibraryFacet.kind == normalized,
            func.coalesce(LibraryWork.hidden, False).is_(False),
            work_visibility_predicate(context),
        )
        .group_by(LibraryFacet.id)
        .order_by(
            func.count(func.distinct(LibraryWork.id)).desc(),
            LibraryFacet.name.asc(),
        )
    ).all()
    result: list[dict[str, Any]] = []
    for facet, book_count in rows:
        row = entity_as_legacy_dict(facet)
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
        LibraryWork.series_name.is_not(None),
        func.trim(LibraryWork.series_name) != "",
        work_visibility_predicate(context),
    ]
    if visibility == "ignored":
        filters.append(LibraryWork.hidden.is_(True))
    elif visibility != "all":
        filters.append(LibraryWork.hidden.is_(False))

    name = func.trim(LibraryWork.series_name).label("name")
    grouped = (
        select(
            name,
            func.count().label("bookCount"),
            func.max(LibraryWork.updated_at).label("latestUpdatedAt"),
        )
        .where(*filters)
        .group_by(name)
        .having(func.count() >= min_books)
        .order_by(func.max(LibraryWork.updated_at).desc(), name.asc())
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
