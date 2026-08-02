"""Typed volume-scoped projections for the library capability."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    UserMediaHistory,
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


def get_media_history(
    db: Session, *, user_id: str, media_version_id: str
) -> dict[str, object] | None:
    history = db.scalar(
        select(UserMediaHistory).where(
            UserMediaHistory.user_id == user_id,
            UserMediaHistory.media_version_id == media_version_id,
        )
    )
    return entity_as_legacy_dict(history) if history is not None else None


def save_media_history(
    db: Session,
    *,
    user_id: str,
    media_version_id: str,
    last_volume_id: str | None,
    now: datetime,
) -> dict[str, object]:
    history = db.scalar(
        select(UserMediaHistory).where(
            UserMediaHistory.user_id == user_id,
            UserMediaHistory.media_version_id == media_version_id,
        )
    )
    if history is None:
        history = UserMediaHistory(
            id=f"py_{uuid4().hex}",
            user_id=user_id,
            media_version_id=media_version_id,
            last_volume_id=last_volume_id,
            created_at=now,
            updated_at=now,
        )
        db.add(history)
    else:
        history.last_volume_id = last_volume_id
        history.updated_at = now
    db.flush()
    return entity_as_legacy_dict(history)


def list_media_histories_for_work(
    db: Session, *, user_id: str, work_id: str
) -> list[dict[str, object]]:
    histories = db.scalars(
        select(UserMediaHistory)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == UserMediaHistory.media_version_id,
        )
        .where(
            UserMediaHistory.user_id == user_id,
            LibraryMediaVersion.work_id == work_id,
        )
        .order_by(UserMediaHistory.updated_at.desc(), UserMediaHistory.id.desc())
    ).all()
    return [entity_as_legacy_dict(history) for history in histories]


def get_media_version(db: Session, media_version_id: str) -> dict[str, object] | None:
    media_version = db.get(LibraryMediaVersion, media_version_id)
    return entity_as_legacy_dict(media_version) if media_version is not None else None


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


def list_volumes_for_media_version(
    db: Session, media_version_id: str
) -> list[dict[str, object]]:
    volumes = db.scalars(
        select(LibraryVolume)
        .where(LibraryVolume.media_version_id == media_version_id)
        .order_by(
            LibraryVolume.sort_order.asc(),
            LibraryVolume.created_at.asc(),
            LibraryVolume.id.asc(),
        )
    ).all()
    return [entity_as_legacy_dict(volume) for volume in volumes]


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


def list_progress_for_media_version(
    db: Session, *, media_version_id: str, user_id: str
) -> list[dict[str, object]]:
    progress_rows = db.scalars(
        select(LibraryReadingProgress)
        .join(
            LibraryVolume,
            LibraryVolume.id == LibraryReadingProgress.volume_id,
        )
        .where(
            LibraryVolume.media_version_id == media_version_id,
            LibraryReadingProgress.user_id == user_id,
        )
        .order_by(
            LibraryReadingProgress.updated_at.desc(),
            LibraryReadingProgress.id.desc(),
        )
    ).all()
    return [entity_as_legacy_dict(progress) for progress in progress_rows]


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
