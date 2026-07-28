"""ORM join helpers for volume/unit/file lookups used by compat adapters."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Table, case, func, select
from sqlalchemy.orm import Session

from app.modules.imports.infrastructure.schema import has_table, reflected_table


def _legacy_table(db: Session, name: str) -> Table | None:
    if not has_table(db, name):
        return None
    return reflected_table(db, name)


def get_volume_with_edition(db: Session, volume_id: str) -> dict[str, Any] | None:
    volume_table = _legacy_table(db, "LibraryVolume")
    edition_table = _legacy_table(db, "LibraryEdition")
    if volume_table is None or edition_table is None:
        return None
    row = db.execute(
        select(volume_table, edition_table)
        .select_from(
            volume_table.join(edition_table, edition_table.c.id == volume_table.c.editionId)
        )
        .where(volume_table.c.id == volume_id)
    ).first()
    if row is None:
        return None
    volume_cols = list(volume_table.c)
    edition_cols = list(edition_table.c)
    payload = {col.name: row[index] for index, col in enumerate(volume_cols)}
    edition_offset = len(volume_cols)
    edition = {col.name: row[edition_offset + index] for index, col in enumerate(edition_cols)}
    payload["workId"] = edition.get("workId")
    payload["mediaKind"] = edition.get("mediaKind")
    payload["format"] = edition.get("format")
    payload["editionHidden"] = edition.get("hidden")
    return payload


def get_unit_with_edition(db: Session, unit_id: str) -> dict[str, Any] | None:
    unit_table = _legacy_table(db, "LibraryReadingUnit")
    edition_table = _legacy_table(db, "LibraryEdition")
    if unit_table is None or edition_table is None:
        return None
    row = db.execute(
        select(unit_table, edition_table)
        .select_from(unit_table.join(edition_table, edition_table.c.id == unit_table.c.editionId))
        .where(unit_table.c.id == unit_id)
    ).first()
    if row is None:
        return None
    unit_cols = list(unit_table.c)
    edition_cols = list(edition_table.c)
    payload = {col.name: row[index] for index, col in enumerate(unit_cols)}
    edition_offset = len(unit_cols)
    edition = {col.name: row[edition_offset + index] for index, col in enumerate(edition_cols)}
    payload["workId"] = edition.get("workId")
    payload["mediaKind"] = edition.get("mediaKind")
    payload["format"] = edition.get("format")
    payload["editionHidden"] = edition.get("hidden")
    return payload


def list_file_paths_for_work(db: Session, work_id: str) -> list[str]:
    file_table = _legacy_table(db, "LibraryFile")
    edition_table = _legacy_table(db, "LibraryEdition")
    if file_table is None or edition_table is None or "path" not in file_table.c:
        return []
    return [
        str(path)
        for path in db.scalars(
            select(file_table.c.path)
            .select_from(file_table.join(edition_table, edition_table.c.id == file_table.c.editionId))
            .where(edition_table.c.workId == work_id, file_table.c.path.is_not(None))
        ).all()
        if path
    ]


def get_primary_edition_row(db: Session, work_id: str) -> dict[str, Any] | None:
    edition_table = _legacy_table(db, "LibraryEdition")
    work_table = _legacy_table(db, "LibraryWork")
    if edition_table is None:
        return None
    stmt = select(edition_table).where(
        edition_table.c.workId == work_id,
        func.coalesce(edition_table.c.hidden, False).is_(False),
    )
    if work_table is not None and "primaryEditionId" in work_table.c:
        stmt = stmt.select_from(
            edition_table.outerjoin(work_table, work_table.c.id == edition_table.c.workId)
        )
        primary_rank = case(
            (edition_table.c.id == work_table.c.primaryEditionId, 0),
            (func.coalesce(edition_table.c.primary, False).is_(True), 1),
            else_=2,
        )
        stmt = stmt.order_by(primary_rank.asc(), edition_table.c.createdAt.asc())
    else:
        order_by = [edition_table.c.createdAt.asc()]
        if "primary" in edition_table.c:
            order_by = [func.coalesce(edition_table.c.primary, False).desc(), *order_by]
        stmt = stmt.order_by(*order_by)
    row = db.execute(stmt.limit(1)).mappings().first()
    return dict(row) if row else None


def get_volume_for_work(db: Session, *, volume_id: str, work_id: str) -> dict[str, Any] | None:
    volume_table = _legacy_table(db, "LibraryVolume")
    edition_table = _legacy_table(db, "LibraryEdition")
    if volume_table is None or edition_table is None:
        return None
    row = db.execute(
        select(volume_table, edition_table)
        .select_from(
            volume_table.join(edition_table, edition_table.c.id == volume_table.c.editionId)
        )
        .where(
            volume_table.c.id == volume_id,
            edition_table.c.workId == work_id,
            func.coalesce(edition_table.c.hidden, False).is_(False),
        )
    ).first()
    if row is None:
        return None
    volume_cols = list(volume_table.c)
    edition_cols = list(edition_table.c)
    payload = {col.name: row[index] for index, col in enumerate(volume_cols)}
    edition_offset = len(volume_cols)
    edition = {col.name: row[edition_offset + index] for index, col in enumerate(edition_cols)}
    payload["sourceWorkId"] = edition.get("workId")
    payload["sourceFormat"] = edition.get("format")
    return payload


def get_edition_with_work_title(db: Session, edition_id: str) -> dict[str, Any] | None:
    edition_table = _legacy_table(db, "LibraryEdition")
    work_table = _legacy_table(db, "LibraryWork")
    if edition_table is None or work_table is None:
        return None
    row = db.execute(
        select(edition_table, work_table.c.title)
        .select_from(edition_table.join(work_table, work_table.c.id == edition_table.c.workId))
        .where(
            edition_table.c.id == edition_id,
            func.coalesce(edition_table.c.hidden, False).is_(False),
        )
    ).first()
    if row is None:
        return None
    edition_cols = list(edition_table.c)
    payload = {col.name: row[index] for index, col in enumerate(edition_cols)}
    payload["targetWorkTitle"] = row[len(edition_cols)]
    return payload


def get_volume_belonging_to_work(db: Session, *, volume_id: str, work_id: str) -> dict[str, Any] | None:
    volume_table = _legacy_table(db, "LibraryVolume")
    edition_table = _legacy_table(db, "LibraryEdition")
    if volume_table is None or edition_table is None:
        return None
    row = db.execute(
        select(volume_table)
        .select_from(
            volume_table.join(edition_table, edition_table.c.id == volume_table.c.editionId)
        )
        .where(volume_table.c.id == volume_id, edition_table.c.workId == work_id)
    ).mappings().first()
    return dict(row) if row else None
