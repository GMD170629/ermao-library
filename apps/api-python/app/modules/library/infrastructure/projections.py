"""Typed volume-scoped projections for the library capability."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    WorkDetailPreference,
)
from app.models.organize import MetadataLookupTask
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def get_detail_preference(
    db: Session, *, user_id: str, work_id: str
) -> dict[str, object] | None:
    preference = db.scalar(
        select(WorkDetailPreference).where(
            WorkDetailPreference.user_id == user_id,
            WorkDetailPreference.work_id == work_id,
        )
    )
    return entity_as_legacy_dict(preference) if preference is not None else None


def get_detail_preferences(
    db: Session, *, user_id: str, work_ids: list[str]
) -> dict[str, dict[str, object]]:
    if not work_ids:
        return {}
    preferences = db.scalars(
        select(WorkDetailPreference).where(
            WorkDetailPreference.user_id == user_id,
            WorkDetailPreference.work_id.in_(work_ids),
        )
    ).all()
    return {
        preference.work_id: entity_as_legacy_dict(preference)
        for preference in preferences
    }


def save_detail_preference(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    selected_tab: str,
    now: datetime,
) -> dict[str, object]:
    preference = db.scalar(
        select(WorkDetailPreference).where(
            WorkDetailPreference.user_id == user_id,
            WorkDetailPreference.work_id == work_id,
        )
    )
    if preference is None:
        preference = WorkDetailPreference(
            id=f"py_{uuid4().hex}",
            user_id=user_id,
            work_id=work_id,
            selected_tab=selected_tab,
            created_at=now,
            updated_at=now,
        )
        db.add(preference)
    else:
        preference.selected_tab = selected_tab
        preference.updated_at = now
    db.flush()
    return entity_as_legacy_dict(preference)


def get_reading_unit_title(db: Session, unit_id: str) -> str | None:
    return db.scalar(
        select(LibraryReadingUnit.title).where(LibraryReadingUnit.id == unit_id)
    )


def list_files_for_volume(db: Session, volume_id: str) -> list[dict[str, object]]:
    files = db.scalars(
        select(LibraryFile)
        .where(LibraryFile.volume_id == volume_id)
        .order_by(LibraryFile.sort_order.asc(), LibraryFile.id.asc())
    ).all()
    return [entity_as_legacy_dict(file) for file in files]




def latest_conversion_metadata(db: Session, volume_id: str) -> dict[str, object] | None:
    metadata = db.scalar(
        select(LibraryMetadata)
        .where(
            LibraryMetadata.volume_id == volume_id,
            LibraryMetadata.source == "conversion",
        )
        .order_by(LibraryMetadata.created_at.desc(), LibraryMetadata.id.desc())
        .limit(1)
    )
    return entity_as_legacy_dict(metadata) if metadata is not None else None




def list_reading_units(db: Session, *, volume_id: str) -> list[dict[str, object]]:
    units = db.scalars(
        select(LibraryReadingUnit)
        .where(LibraryReadingUnit.volume_id == volume_id)
        .order_by(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.id.asc(),
        )
    ).all()
    return [entity_as_legacy_dict(unit) for unit in units]


def reading_units_page(
    db: Session,
    *,
    volume_id: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, object]], int]:
    total = int(
        db.scalar(
            select(func.count(LibraryReadingUnit.id)).where(
                LibraryReadingUnit.volume_id == volume_id
            )
        )
        or 0
    )
    units = db.scalars(
        select(LibraryReadingUnit)
        .where(LibraryReadingUnit.volume_id == volume_id)
        .order_by(
            LibraryReadingUnit.sort_order.asc(),
            LibraryReadingUnit.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [entity_as_legacy_dict(unit) for unit in units], total


def latest_metadata_lookup_for_work(
    db: Session, work_id: str
) -> dict[str, object] | None:
    task = db.scalar(
        select(MetadataLookupTask)
        .where(MetadataLookupTask.work_id == work_id)
        .order_by(
            MetadataLookupTask.created_at.desc(),
            MetadataLookupTask.id.desc(),
        )
        .limit(1)
    )
    return entity_as_legacy_dict(task) if task is not None else None


def latest_metadata_lookups_for_works(
    db: Session, work_ids: list[str]
) -> dict[str, dict[str, object]]:
    if not work_ids:
        return {}
    rank = (
        func.row_number()
        .over(
            partition_by=MetadataLookupTask.work_id,
            order_by=(
                MetadataLookupTask.created_at.desc(),
                MetadataLookupTask.id.desc(),
            ),
        )
        .label("lookup_rank")
    )
    ranked = (
        select(MetadataLookupTask.__table__, rank)
        .where(MetadataLookupTask.work_id.in_(work_ids))
        .subquery()
    )
    rows = db.execute(select(ranked).where(ranked.c.lookup_rank == 1)).mappings()
    result: dict[str, dict[str, object]] = {}
    for row in rows:
        value = dict(row)
        value.pop("lookup_rank", None)
        result[str(row["workId"])] = value
    return result
