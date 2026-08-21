"""Typed ReadableResource-scoped projections for the library capability."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    LibraryResourceAsset,
    ReadableResourceNavigationUnit,
    BookDetailPreference,
)
from app.models.organize import MetadataLookupTask
from app.modules.library.infrastructure.books import entity_record


def get_detail_preference(
    db: Session, *, user_id: str, book_id: str
) -> dict[str, object] | None:
    preference = db.scalar(
        select(BookDetailPreference).where(
            BookDetailPreference.user_id == user_id,
            BookDetailPreference.book_id == book_id,
        )
    )
    return entity_record(preference) if preference is not None else None


def get_detail_preferences(
    db: Session, *, user_id: str, book_ids: list[str]
) -> dict[str, dict[str, object]]:
    if not book_ids:
        return {}
    preferences = db.scalars(
        select(BookDetailPreference).where(
            BookDetailPreference.user_id == user_id,
            BookDetailPreference.book_id.in_(book_ids),
        )
    ).all()
    return {
        preference.book_id: entity_record(preference)
        for preference in preferences
    }


def save_detail_preference(
    db: Session,
    *,
    user_id: str,
    book_id: str,
    selected_tab: str,
    now: datetime,
) -> dict[str, object]:
    preference = db.scalar(
        select(BookDetailPreference).where(
            BookDetailPreference.user_id == user_id,
            BookDetailPreference.book_id == book_id,
        )
    )
    if preference is None:
        preference = BookDetailPreference(
            id=f"py_{uuid4().hex}",
            user_id=user_id,
            book_id=book_id,
            selected_tab=selected_tab,
            created_at=now,
            updated_at=now,
        )
        db.add(preference)
    else:
        preference.selected_tab = selected_tab
        preference.updated_at = now
    db.flush()
    return entity_record(preference)


def get_reading_unit_title(db: Session, unit_id: str) -> str | None:
    return db.scalar(
        select(ReadableResourceNavigationUnit.title).where(ReadableResourceNavigationUnit.id == unit_id)
    )


def list_assets_for_resource(db: Session, resource_id: str) -> list[dict[str, object]]:
    assets = db.scalars(
        select(LibraryResourceAsset)
        .where(LibraryResourceAsset.resource_id == resource_id)
        .order_by(
            LibraryResourceAsset.sequence_index.asc(),
            LibraryResourceAsset.id.asc(),
        )
    ).all()
    return [entity_record(asset) for asset in assets]


def list_reading_units(db: Session, *, resource_id: str) -> list[dict[str, object]]:
    units = db.scalars(
        select(ReadableResourceNavigationUnit)
        .where(ReadableResourceNavigationUnit.resource_id == resource_id)
        .order_by(
            ReadableResourceNavigationUnit.sort_order.asc(),
            ReadableResourceNavigationUnit.id.asc(),
        )
    ).all()
    return [entity_record(unit) for unit in units]


def reading_units_page(
    db: Session,
    *,
    resource_id: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    total = int(
        db.scalar(
            select(func.count(ReadableResourceNavigationUnit.id)).where(
                ReadableResourceNavigationUnit.resource_id == resource_id
            )
        )
        or 0
    )
    units = db.scalars(
        select(ReadableResourceNavigationUnit)
        .where(ReadableResourceNavigationUnit.resource_id == resource_id)
        .order_by(
            ReadableResourceNavigationUnit.sort_order.asc(),
            ReadableResourceNavigationUnit.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [entity_record(unit) for unit in units], total


def latest_metadata_lookup_for_book(
    db: Session, book_id: str
) -> dict[str, object] | None:
    task = db.scalar(
        select(MetadataLookupTask)
        .where(MetadataLookupTask.book_id == book_id)
        .order_by(
            MetadataLookupTask.created_at.desc(),
            MetadataLookupTask.id.desc(),
        )
        .limit(1)
    )
    return entity_record(task) if task is not None else None


def latest_metadata_lookups_for_books(
    db: Session, book_ids: list[str]
) -> dict[str, dict[str, object]]:
    if not book_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=MetadataLookupTask.book_id,
            order_by=(
                MetadataLookupTask.created_at.desc(),
                MetadataLookupTask.id.desc(),
            ),
        )
        .label("lookup_rank")
    )
    ranked = (
        select(MetadataLookupTask.__table__, rank)
        .where(MetadataLookupTask.book_id.in_(book_ids))
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.lookup_rank == 1)).mappings()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        value = dict(row)
        value.pop("lookup_rank", None)
        result[str(row["bookId"])] = value
    return result
