"""ORM persistence for work and media-version structure commands."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
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
