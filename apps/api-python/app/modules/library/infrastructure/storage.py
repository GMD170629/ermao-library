"""ORM queries and writes for library files, covers, and managed paths."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryEdition,
    LibraryFile,
    LibraryVolume,
    LibraryWork,
)
from app.modules.library.infrastructure import projections


def get_file(db: Session, file_id: str) -> dict[str, object] | None:
    rows = projections.select_existing_rows(
        db,
        LibraryFile,
        "LibraryFile",
        filters=(LibraryFile.id == file_id,),
        limit=1,
    )
    return rows[0] if rows else None


def first_file_for_edition(
    db: Session,
    *,
    edition_id: str,
    volume_id: str | None = None,
) -> dict[str, object] | None:
    filters = [LibraryFile.edition_id == edition_id]
    if volume_id is not None:
        filters.append(LibraryFile.volume_id == volume_id)
    rows = projections.select_existing_rows(
        db,
        LibraryFile,
        "LibraryFile",
        filters=filters,
        order_by=(
            LibraryFile.sort_order.asc(),
            LibraryFile.created_at.asc(),
            LibraryFile.id.asc(),
        ),
        limit=1,
    )
    return rows[0] if rows else None


def get_cover_record(
    db: Session,
    *,
    work_id: str | None = None,
    edition_id: str | None = None,
    volume_id: str | None = None,
) -> dict[str, object] | None:
    if work_id is not None:
        rows = projections.select_existing_rows(
            db,
            LibraryWork,
            "LibraryWork",
            filters=(LibraryWork.id == work_id,),
            limit=1,
        )
    elif edition_id is not None:
        rows = projections.select_existing_rows(
            db,
            LibraryEdition,
            "LibraryEdition",
            filters=(LibraryEdition.id == edition_id,),
            limit=1,
        )
    elif volume_id is not None:
        rows = projections.select_existing_rows(
            db,
            LibraryVolume,
            "LibraryVolume",
            filters=(LibraryVolume.id == volume_id,),
            limit=1,
        )
    else:
        rows = []
    return rows[0] if rows else None


def update_cover_record(
    db: Session,
    *,
    record_type: str,
    record_id: str,
    cover_path: str,
    cover_status: str | None,
    now: datetime,
) -> None:
    if record_type == "LibraryWork":
        values: dict[str, object] = {
            "cover_path": cover_path,
            "updated_at": now,
        }
        if cover_status is not None:
            values["cover_status"] = cover_status
        db.execute(
            update(LibraryWork)
            .where(LibraryWork.id == record_id)
            .values(**values)
        )
    elif record_type == "LibraryEdition":
        values = {"cover_path": cover_path, "updated_at": now}
        if cover_status is not None:
            values["cover_status"] = cover_status
        db.execute(
            update(LibraryEdition)
            .where(LibraryEdition.id == record_id)
            .values(**values)
        )
    elif record_type == "LibraryVolume":
        db.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == record_id)
            .values(cover_path=cover_path, updated_at=now)
        )
    db.flush()


def preferred_work_cover_path(db: Session, work_id: str) -> str | None:
    work = db.execute(
        select(LibraryWork.primary_edition_id).where(LibraryWork.id == work_id)
    ).first()
    primary_edition_id = work.primary_edition_id if work is not None else None
    if primary_edition_id:
        volume_cover = db.scalar(
            select(LibraryVolume.cover_path)
            .where(
                LibraryVolume.edition_id == primary_edition_id,
                LibraryVolume.cover_path.is_not(None),
                LibraryVolume.cover_path != "",
            )
            .order_by(
                case((LibraryVolume.volume_index.is_(None), 1), else_=0),
                LibraryVolume.volume_index.asc(),
                LibraryVolume.sort_order.asc(),
                LibraryVolume.created_at.asc(),
                LibraryVolume.id.asc(),
            )
            .limit(1)
        )
        if volume_cover:
            return str(volume_cover)
        edition_cover = db.scalar(
            select(LibraryEdition.cover_path).where(
                LibraryEdition.id == primary_edition_id
            )
        )
        if edition_cover:
            return str(edition_cover)
    edition_cover = db.scalar(
        select(LibraryEdition.cover_path)
        .where(
            LibraryEdition.work_id == work_id,
            func.coalesce(LibraryEdition.hidden, False).is_(False),
            LibraryEdition.cover_path.is_not(None),
            LibraryEdition.cover_path != "",
        )
        .order_by(
            case((LibraryEdition.is_primary.is_(True), 0), else_=1),
            LibraryEdition.created_at.asc(),
            LibraryEdition.id.asc(),
        )
        .limit(1)
    )
    return str(edition_cover) if edition_cover else None


def update_work_cover(
    db: Session,
    *,
    work_id: str,
    cover_path: str,
    cover_status: str,
    now: datetime,
) -> bool:
    result = db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            cover_path=cover_path,
            cover_status=cover_status,
            updated_at=now,
        )
    )
    db.flush()
    return bool(result.rowcount)


def collect_storage_values(
    db: Session,
    work_id: str,
) -> tuple[str | None, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    work_cover = db.scalar(
        select(LibraryWork.cover_path).where(LibraryWork.id == work_id)
    )
    editions = projections.select_existing_rows(
        db,
        LibraryEdition,
        "LibraryEdition",
        filters=(LibraryEdition.work_id == work_id,),
        order_by=(LibraryEdition.created_at.asc(), LibraryEdition.id.asc()),
    )
    edition_ids = [str(edition["id"]) for edition in editions]
    if not edition_ids:
        return work_cover, editions, [], []
    volumes = projections.select_existing_rows(
        db,
        LibraryVolume,
        "LibraryVolume",
        filters=(LibraryVolume.edition_id.in_(edition_ids),),
    )
    files = projections.select_existing_rows(
        db,
        LibraryFile,
        "LibraryFile",
        filters=(LibraryFile.edition_id.in_(edition_ids),),
    )
    return work_cover, editions, volumes, files
