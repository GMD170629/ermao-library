"""Book, ReadableResource, and ResourceAsset storage projections."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    LibraryBook,
    LibraryBookMetadata,
    LibraryReadableResource,
    LibraryReadableResourceMetadata,
    LibraryResourceAsset,
)
from app.modules.library.infrastructure.books import entity_record


def get_asset(db: Session, asset_id: str) -> dict[str, object] | None:
    asset = db.get(LibraryResourceAsset, asset_id)
    return entity_record(asset) if asset is not None else None


def first_asset_for_resource(
    db: Session, *, resource_id: str
) -> dict[str, object] | None:
    asset = db.scalar(
        select(LibraryResourceAsset)
        .where(
            LibraryResourceAsset.resource_id == resource_id,
            LibraryResourceAsset.import_state == "READY",
        )
        .order_by(
            LibraryResourceAsset.sequence_index.asc(),
            LibraryResourceAsset.created_at.asc(),
            LibraryResourceAsset.id.asc(),
        )
        .limit(1)
    )
    return entity_record(asset) if asset is not None else None


def get_cover_record(
    db: Session,
    *,
    book_id: str | None = None,
    resource_id: str | None = None,
) -> dict[str, object] | None:
    if book_id is not None:
        record = db.get(LibraryBookMetadata, book_id)
    elif resource_id is not None:
        record = db.get(LibraryReadableResourceMetadata, resource_id)
    else:
        record = None
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
    if record_type == "LibraryBook":
        model = LibraryBookMetadata
        identifier = model.book_id
    elif record_type == "LibraryReadableResource":
        model = LibraryReadableResourceMetadata
        identifier = model.resource_id
    else:
        raise ValueError(f"Unsupported cover record type: {record_type}")
    values: dict[str, object] = {"cover_path": cover_path, "updated_at": now}
    if cover_status is not None:
        values["cover_status"] = cover_status
    db.execute(update(model).where(identifier == record_id).values(**values))
    db.flush()


def preferred_book_cover_path(db: Session, book_id: str) -> str | None:
    cover = db.scalar(
        select(LibraryReadableResourceMetadata.cover_path)
        .join(
            LibraryReadableResource,
            LibraryReadableResource.id == LibraryReadableResourceMetadata.resource_id,
        )
        .where(
            LibraryReadableResource.book_id == book_id,
            LibraryReadableResource.enablement_state == "ENABLED",
            LibraryReadableResourceMetadata.cover_path.is_not(None),
            LibraryReadableResourceMetadata.cover_path != "",
        )
        .order_by(
            LibraryReadableResource.created_at.asc(),
            LibraryReadableResource.id.asc(),
        )
        .limit(1)
    )
    return str(cover) if cover else None


def update_book_cover(
    db: Session,
    *,
    book_id: str,
    cover_path: str,
    cover_status: str,
    now: datetime,
) -> bool:
    result = db.execute(
        update(LibraryBookMetadata)
        .where(LibraryBookMetadata.book_id == book_id)
        .values(
            cover_path=cover_path,
            cover_status=cover_status,
            updated_at=now,
        )
    )
    return bool(result.rowcount)


def update_book_covers(
    db: Session,
    rows: tuple[dict[str, object], ...],
) -> int:
    if not rows:
        return 0
    db.execute(update(LibraryBookMetadata), list(rows))
    return len(rows)


def collect_book_storage_values(
    db: Session, book_id: str
) -> tuple[
    str | None,
    list[dict[str, object]],
    list[dict[str, object]],
]:
    book_cover = db.scalar(
        select(LibraryBookMetadata.cover_path).where(
            LibraryBookMetadata.book_id == book_id
        )
    )
    resources = db.scalars(
        select(LibraryReadableResource)
        .where(LibraryReadableResource.book_id == book_id)
        .order_by(
            LibraryReadableResource.created_at.asc(),
            LibraryReadableResource.id.asc(),
        )
    ).all()
    resource_ids = [resource.id for resource in resources]
    assets = (
        db.scalars(
            select(LibraryResourceAsset)
            .where(LibraryResourceAsset.resource_id.in_(resource_ids))
            .order_by(
                LibraryResourceAsset.sequence_index.asc(),
                LibraryResourceAsset.id.asc(),
            )
        ).all()
        if resource_ids
        else []
    )
    return (
        book_cover,
        [entity_record(resource) for resource in resources],
        [entity_record(asset) for asset in assets],
    )
