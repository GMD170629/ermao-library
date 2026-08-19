"""ORM persistence for work and media-version structure commands."""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryWork,
)

STATUS_RANK = {"UNREAD": 0, "READING": 1, "FINISHED": 2}


def entity_as_legacy_dict(entity: object) -> dict[str, Any]:
    mapper = sa_inspect(entity).mapper
    return {
        prop.columns[0].name: getattr(entity, prop.key) for prop in mapper.column_attrs
    }


def get_visible_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.scalar(
        select(LibraryWork).where(
            LibraryWork.id == work_id,
            LibraryWork.hidden.is_(False),
        )
    )
    return entity_as_legacy_dict(work) if work is not None else None


def get_work(db: Session, work_id: str) -> dict[str, Any] | None:
    work = db.get(LibraryWork, work_id)
    return entity_as_legacy_dict(work) if work is not None else None


def list_works_by_ids(
    db: Session, work_ids: tuple[str, ...] | list[str]
) -> list[dict[str, Any]]:
    if not work_ids:
        return []
    rows = db.scalars(select(LibraryWork).where(LibraryWork.id.in_(work_ids))).all()
    return [entity_as_legacy_dict(row) for row in rows]


def update_work_fields(
    db: Session, work_id: str, values: dict[str, Any]
) -> dict[str, Any] | None:
    mapping = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(LibraryWork).mapper.column_attrs
    }
    payload = {mapping[key]: value for key, value in values.items() if key in mapping}
    if payload:
        work = db.scalar(
            update(LibraryWork)
            .where(LibraryWork.id == work_id)
            .values(**payload)
            .returning(LibraryWork)
        )
        return entity_as_legacy_dict(work) if work is not None else None
    return get_work(db, work_id)


def update_work_fields_bulk(
    db: Session,
    updates: tuple[tuple[str, dict[str, Any]], ...],
) -> int:
    mapping = {
        prop.columns[0].name: prop.key
        for prop in sa_inspect(LibraryWork).mapper.column_attrs
    }
    rows = [
        {
            "id": work_id,
            **{
                mapping[key]: value
                for key, value in values.items()
                if key in mapping and key != "id"
            },
        }
        for work_id, values in updates
        if values
    ]
    if rows:
        db.execute(update(LibraryWork), rows)
    return len(rows)


def list_duplicate_identity_groups(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
            func.count(LibraryWork.id).label("count"),
        )
        .where(LibraryWork.hidden.is_(False))
        .group_by(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
        )
        .having(func.count(LibraryWork.id) > 1)
    ).all()
    return [
        {
            "normalizedTitle": row.normalized_title,
            "normalizedAuthor": row.normalized_author,
            "count": int(row.count),
        }
        for row in rows
    ]


def list_duplicate_identity_page(
    db: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int, int]:
    duplicate_count = func.count(LibraryWork.id).label("work_count")
    statement = (
        select(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
            duplicate_count,
            func.count().over().label("total_count"),
        )
        .where(LibraryWork.hidden.is_(False))
        .group_by(
            LibraryWork.normalized_title,
            LibraryWork.normalized_author,
        )
        .having(duplicate_count > 1)
        .order_by(
            duplicate_count.desc(),
            LibraryWork.normalized_title.asc(),
            LibraryWork.normalized_author.asc(),
        )
    )

    def fetch(target_page: int) -> list[Any]:
        return db.execute(
            statement.limit(page_size).offset((target_page - 1) * page_size)
        ).all()

    rows = fetch(page)
    if rows:
        total = int(rows[0].total_count)
        clamped_page = page
    else:
        grouped = (
            select(
                LibraryWork.normalized_title,
                LibraryWork.normalized_author,
            )
            .where(LibraryWork.hidden.is_(False))
            .group_by(
                LibraryWork.normalized_title,
                LibraryWork.normalized_author,
            )
            .having(func.count(LibraryWork.id) > 1)
            .subquery()
        )
        total = int(db.scalar(select(func.count()).select_from(grouped)) or 0)
        clamped_page = min(page, max(1, (total + page_size - 1) // page_size))
        if total and clamped_page != page:
            rows = fetch(clamped_page)

    identity_filters = [
        and_(
            LibraryWork.normalized_title == row.normalized_title,
            LibraryWork.normalized_author.is_(None)
            if row.normalized_author is None
            else LibraryWork.normalized_author == row.normalized_author,
        )
        for row in rows
    ]
    works = (
        db.scalars(
            select(LibraryWork)
            .where(
                LibraryWork.hidden.is_(False),
                or_(*identity_filters),
            )
            .order_by(
                LibraryWork.normalized_title.asc(),
                LibraryWork.normalized_author.asc(),
                LibraryWork.id.asc(),
            )
        ).all()
        if identity_filters
        else []
    )
    works_by_identity: dict[tuple[str, str | None], list[dict[str, Any]]] = {}
    for work in works:
        identity = (work.normalized_title, work.normalized_author)
        works_by_identity.setdefault(identity, []).append(entity_as_legacy_dict(work))
    groups = [
        {
            "normalizedTitle": row.normalized_title,
            "normalizedAuthor": row.normalized_author,
            "count": int(row.work_count),
            "works": works_by_identity.get(
                (row.normalized_title, row.normalized_author), []
            ),
        }
        for row in rows
    ]
    return groups, total, clamped_page


def list_works_for_normalized_identity(
    db: Session, *, normalized_title: str, normalized_author: str
) -> list[dict[str, Any]]:
    works = db.scalars(
        select(LibraryWork).where(
            LibraryWork.normalized_title == normalized_title,
            LibraryWork.normalized_author == normalized_author,
            LibraryWork.hidden.is_(False),
        )
    ).all()
    return [entity_as_legacy_dict(work) for work in works]
