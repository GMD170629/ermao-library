"""Resource-scoped library file, cover, and storage queries."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    LibraryResourceAsset,
    LibraryReadableResource,
    LibraryReadableResource,
    LibraryBook,
)
from app.modules.library.infrastructure.books import entity_record


def get_file(db: Session, asset_id: str) -> dict[str, object] | None:
    file = db.get(LibraryResourceAsset, asset_id)
    return entity_record(file) if file is not None else None


def first_file_for_volume(db: Session, *, resource_id: str) -> dict[str, object] | None:
    file = db.scalar(
        select(LibraryResourceAsset)
        .where(LibraryResourceAsset.resource_id == resource_id)
        .order_by(
            LibraryResourceAsset.sort_order.asc(),
            LibraryResourceAsset.created_at.asc(),
            LibraryResourceAsset.id.asc(),
        )
        .limit(1)
    )
    return entity_record(file) if file is not None else None


def get_cover_record(
    db: Session,
    *,
    book_id: str | None = None,
    resource_id: str | None = None,
) -> dict[str, object] | None:
    record = (
        db.get(LibraryBook, book_id)
        if book_id is not None
        else db.get(LibraryReadableResource, resource_id)
        if resource_id is not None
        else None
    )
    return entity_record(record) if record is not None else None


def update_cover_record(
    db: Session,
    *,
    record_type: str,
    record_id: str,
    cover_path: str,
    cover_status: str | None,
    now: datetime,
) -> None:
    model = LibraryBook if record_type == "LibraryBook" else LibraryReadableResource
    values: dict[str, object] = {"cover_path": cover_path, "updated_at": now}
    if cover_status is not None:
        values["cover_status"] = cover_status
    db.execute(update(model).where(model.id == record_id).values(**values))
    db.flush()


def preferred_work_cover_path(db: Session, book_id: str) -> str | None:
    cover = db.scalar(
        select(LibraryReadableResource.cover_path)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResource.resource_id,
        )
        .where(
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.hidden.is_(False),
            LibraryReadableResource.cover_path.is_not(None),
            LibraryReadableResource.cover_path != "",
        )
        .order_by(
            LibraryReadableResource.sort_order.asc(),
            LibraryReadableResource.created_at.asc(),
            LibraryReadableResource.id.asc(),
        )
        .limit(1)
    )
    return str(cover) if cover else None


def update_work_cover(
    db: Session,
    *,
    book_id: str,
    cover_path: str,
    cover_status: str,
    now: datetime,
) -> bool:
    result = db.execute(
        update(LibraryBook)
        .where(LibraryBook.id == book_id)
        .values(
            cover_path=cover_path,
            cover_status=cover_status,
            updated_at=now,
        )
    )
    return bool(result.rowcount)


def update_work_covers(
    db: Session,
    rows: tuple[dict[str, object], ...],
) -> int:
    if not rows:
        return 0
    db.execute(update(LibraryBook), list(rows))
    return len(rows)


def collect_storage_values(
    db: Session, book_id: str
) -> tuple[
    str | None,
    list[dict[str, object]],
    list[dict[str, object]],
]:
    work_cover = db.scalar(
        select(LibraryBook.cover_path).where(LibraryBook.id == book_id)
    )
    volumes = db.scalars(
        select(LibraryReadableResource)
        .join(LibraryReadableResource, LibraryReadableResource.id == LibraryReadableResource.resource_id)
        .where(LibraryReadableResource.book_id == book_id)
        .order_by(
            LibraryReadableResource.sort_order.asc(),
            LibraryReadableResource.created_at.asc(),
            LibraryReadableResource.id.asc(),
        )
    ).all()
    resource_ids = [volume.id for volume in volumes]
    files = (
        db.scalars(
            select(LibraryResourceAsset).where(LibraryResourceAsset.resource_id.in_(resource_ids))
        ).all()
        if resource_ids
        else []
    )
    return (
        work_cover,
        [entity_record(volume) for volume in volumes],
        [entity_record(file) for file in files],
    )
