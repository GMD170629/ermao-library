"""Model-specific ORM writes used while the import pipeline is decomposed.

Every operation is bound to one declared ORM model.  This module deliberately
does not accept table names or model classes and never owns a transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import ImportAsset, ImportLog, ImportTask
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
)
from app.models.organize import MetadataLookupTask, OrganizeJob


def insert_import_task(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(ImportTask.__table__).values(values))
    db.flush()
    return dict(values)


def update_import_task(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(ImportTask.__table__).where(ImportTask.id == row_id).values(values))


def insert_import_asset(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(ImportAsset.__table__).values(values))
    db.flush()
    return dict(values)


def update_import_asset(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(ImportAsset.__table__).where(ImportAsset.id == row_id).values(values))


def insert_import_log(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(ImportLog.__table__).values(values))
    db.flush()
    return dict(values)


def insert_library_work(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryWork.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_work(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(LibraryWork.__table__).where(LibraryWork.id == row_id).values(values))


def insert_library_edition(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryEdition.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_edition(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(LibraryEdition.__table__).where(LibraryEdition.id == row_id).values(values))


def insert_library_volume(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryVolume.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_volume(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(LibraryVolume.__table__).where(LibraryVolume.id == row_id).values(values))


def insert_library_file(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryFile.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_file(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(LibraryFile.__table__).where(LibraryFile.id == row_id).values(values))


def get_library_file(db: Session, row_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryFile.__table__).where(LibraryFile.id == row_id)
    ).mappings().first()
    return dict(row) if row else None


def insert_library_reading_unit(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryReadingUnit.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_reading_unit(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(
        update(LibraryReadingUnit.__table__)
        .where(LibraryReadingUnit.id == row_id)
        .values(values)
    )


def get_library_reading_unit(db: Session, row_id: str) -> dict[str, Any] | None:
    row = db.execute(
        select(LibraryReadingUnit.__table__).where(LibraryReadingUnit.id == row_id)
    ).mappings().first()
    return dict(row) if row else None


def delete_library_reading_unit(db: Session, row_id: str) -> None:
    db.execute(delete(LibraryReadingUnit).where(LibraryReadingUnit.id == row_id))


def insert_library_metadata(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(LibraryMetadata.__table__).values(values))
    db.flush()
    return dict(values)


def update_library_reading_progress(
    db: Session,
    row_id: str,
    values: dict[str, Any],
) -> None:
    db.execute(
        update(LibraryReadingProgress.__table__)
        .where(LibraryReadingProgress.id == row_id)
        .values(values)
    )


def update_library_consumption_state(
    db: Session,
    row_id: str,
    values: dict[str, Any],
) -> None:
    db.execute(
        update(LibraryConsumptionState.__table__)
        .where(LibraryConsumptionState.id == row_id)
        .values(values)
    )


def insert_organize_job(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(OrganizeJob.__table__).values(values))
    db.flush()
    return dict(values)


def update_organize_job(db: Session, row_id: str, values: dict[str, Any]) -> None:
    db.execute(update(OrganizeJob.__table__).where(OrganizeJob.id == row_id).values(values))


def insert_metadata_lookup_task(db: Session, values: dict[str, Any]) -> dict[str, Any]:
    db.execute(insert(MetadataLookupTask.__table__).values(values))
    db.flush()
    return dict(values)


def update_metadata_lookup_task(
    db: Session,
    row_id: str,
    values: dict[str, Any],
) -> None:
    db.execute(
        update(MetadataLookupTask.__table__)
        .where(MetadataLookupTask.id == row_id)
        .values(values)
    )
