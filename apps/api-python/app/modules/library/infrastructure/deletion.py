"""ORM cascade deletion for library works, editions, and volumes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Table, delete, func, inspect as sa_inspect, or_, select, update
from sqlalchemy.orm import Session

from app.models.import_pipeline import DownloadTask, ImportAsset, ImportTask, KindleSendTask
from app.db.base import Base
from app.models.library import (
    LibraryConsumptionState,
    LibraryEdition,
    LibraryFile,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    WorkDetailPreference,
)
from app.models.organize import (
    DuplicateCandidate,
    MetadataLookupTask,
    MetadataSuggestion,
    OrganizeJob,
)
from app.models.settings import ReaderBookPreference, ReaderProgressCursor
from app.models.shelf import ShelfWork
from app.modules.library.infrastructure import operations as library_operations


def _has_table(db: Session, table: str) -> bool:
    return sa_inspect(db.connection()).has_table(table)


def _legacy_table(db: Session, table: str) -> Table | None:
    if not _has_table(db, table):
        return None
    return Base.metadata.tables.get(table)


def _has_column(db: Session, table: str, column: str) -> bool:
    if not _has_table(db, table):
        return False
    declared = Base.metadata.tables.get(table)
    return declared is not None and column in declared.c


def _edition_ids_subquery(work_id: str):
    return select(LibraryEdition.id).where(LibraryEdition.work_id == work_id)


def _volume_ids_subquery(work_id: str):
    return select(LibraryVolume.id).where(
        LibraryVolume.edition_id.in_(_edition_ids_subquery(work_id))
    )


def _file_ids_subquery(work_id: str):
    return select(LibraryFile.id).where(
        LibraryFile.edition_id.in_(_edition_ids_subquery(work_id))
    )


def _delete_where(db: Session, model: type, *filters: Any) -> int:
    if not _has_table(db, model.__tablename__):
        return 0
    result = db.execute(delete(model).where(*filters))
    return int(result.rowcount or 0)


def delete_work_records(db: Session, work_id: str) -> dict[str, Any]:
    """Cascade-delete one work and linked rows without owning the transaction."""

    if not _has_table(db, "LibraryWork"):
        return {"deleted": False, "deletedDatabaseRecords": 0}

    deleted_records = 0
    has_editions = _has_table(db, "LibraryEdition")
    edition_ids = _edition_ids_subquery(work_id)
    volume_ids = _volume_ids_subquery(work_id)
    file_ids = _file_ids_subquery(work_id)

    if _has_table(db, "ImportTask"):
        import_filters = [ImportTask.work_id == work_id]
        if has_editions:
            import_filters.append(ImportTask.edition_id.in_(edition_ids))
            import_filters.append(ImportTask.volume_id.in_(volume_ids))
        db.execute(
            update(ImportTask)
            .where(or_(*import_filters))
            .values(work_id=None, edition_id=None, volume_id=None)
        )

    if _has_table(db, "KindleSendTask"):
        kindle_filters = [KindleSendTask.work_id == work_id]
        if has_editions:
            kindle_filters.extend(
                [
                    KindleSendTask.edition_id.in_(edition_ids),
                    KindleSendTask.volume_id.in_(volume_ids),
                    KindleSendTask.file_id.in_(file_ids),
                ]
            )
        db.execute(
            update(KindleSendTask)
            .where(or_(*kindle_filters))
            .values(work_id=None, edition_id=None, volume_id=None, file_id=None)
        )

    if _has_table(db, "DownloadTask") and _has_column(db, "DownloadTask", "bookId"):
        db.execute(
            update(DownloadTask)
            .where(DownloadTask.book_id == work_id)
            .values(book_id=None)
        )

    job_ids = select(OrganizeJob.id).where(OrganizeJob.work_id == work_id)
    if _has_table(db, "OrganizeJob"):
        if _has_table(db, "MetadataSuggestion"):
            deleted_records += _delete_where(
                db, MetadataSuggestion, MetadataSuggestion.job_id.in_(job_ids)
            )
        if _has_table(db, "DuplicateCandidate"):
            deleted_records += _delete_where(
                db,
                DuplicateCandidate,
                or_(
                    DuplicateCandidate.job_id.in_(job_ids),
                    DuplicateCandidate.target_work_id == work_id,
                ),
            )
    elif _has_table(db, "DuplicateCandidate"):
        deleted_records += _delete_where(
            db, DuplicateCandidate, DuplicateCandidate.target_work_id == work_id
        )

    deleted_records += _delete_where(
        db, MetadataLookupTask, MetadataLookupTask.work_id == work_id
    )
    deleted_records += _delete_where(db, OrganizeJob, OrganizeJob.work_id == work_id)
    deleted_records += _delete_where(
        db, ReaderBookPreference, ReaderBookPreference.work_id == work_id
    )
    deleted_records += _delete_where(
        db, ReaderProgressCursor, ReaderProgressCursor.work_id == work_id
    )
    deleted_records += _delete_where(
        db, WorkDetailPreference, WorkDetailPreference.work_id == work_id
    )
    deleted_records += _delete_where(
        db, LibraryConsumptionState, LibraryConsumptionState.work_id == work_id
    )
    deleted_records += _delete_where(db, ShelfWork, ShelfWork.work_id == work_id)
    deleted_records += _delete_where(
        db, LibraryReadingProgress, LibraryReadingProgress.work_id == work_id
    )

    if has_editions:
        edition_id_list = list(db.scalars(edition_ids).all())
        for edition_id in edition_id_list:
            if _has_table(db, "LibraryEditionFacet"):
                library_operations.delete_edition_facets_for_edition(db, str(edition_id))
        deleted_records += _delete_where(
            db, LibraryReadingUnit, LibraryReadingUnit.edition_id.in_(edition_ids)
        )
        deleted_records += _delete_where(
            db, LibraryMetadata, LibraryMetadata.edition_id.in_(edition_ids)
        )
        deleted_records += _delete_where(
            db, LibraryFile, LibraryFile.edition_id.in_(edition_ids)
        )
        deleted_records += _delete_where(
            db, LibraryVolume, LibraryVolume.edition_id.in_(edition_ids)
        )
        deleted_records += _delete_where(
            db, LibraryEdition, LibraryEdition.work_id == work_id
        )

    if _has_table(db, "LibraryWorkFacet"):
        library_operations.delete_work_facets_for_work(db, work_id)

    result = db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))
    deleted = bool(result.rowcount)
    deleted_records += int(result.rowcount or 0)
    db.flush()
    return {"deleted": deleted, "deletedDatabaseRecords": deleted_records}


def clear_file_references(db: Session, file_ids: list[str]) -> None:
    if not file_ids:
        return
    if _has_table(db, "ImportAsset"):
        db.execute(
            update(ImportAsset)
            .where(ImportAsset.file_id.in_(file_ids))
            .values(file_id=None)
        )
    if _has_table(db, "KindleSendTask"):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.file_id.in_(file_ids))
            .values(file_id=None)
        )


def list_files_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryFile")
    if table is None:
        return []
    rows = db.execute(select(table).where(table.c.editionId == edition_id)).mappings().all()
    return [dict(row) for row in rows]


def list_files_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryFile")
    if table is None:
        return []
    rows = db.execute(select(table).where(table.c.volumeId == volume_id)).mappings().all()
    return [dict(row) for row in rows]


def list_volume_covers_for_edition(db: Session, edition_id: str) -> list[dict[str, Any]]:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return []
    rows = db.execute(select(table).where(table.c.editionId == edition_id)).mappings().all()
    return [dict(row) for row in rows]


def get_edition_for_work(
    db: Session, *, edition_id: str, work_id: str
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryEdition")
    if table is None:
        return None
    row = db.execute(
        select(table).where(table.c.id == edition_id, table.c.workId == work_id)
    ).mappings().first()
    return dict(row) if row else None


def get_volume_for_edition(
    db: Session, *, volume_id: str, edition_id: str
) -> dict[str, Any] | None:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return None
    row = db.execute(
        select(table).where(table.c.id == volume_id, table.c.editionId == edition_id)
    ).mappings().first()
    return dict(row) if row else None


def count_volumes_for_edition(db: Session, edition_id: str) -> int:
    table = _legacy_table(db, "LibraryVolume")
    if table is None:
        return 0
    return int(
        db.scalar(select(func.count()).select_from(table).where(table.c.editionId == edition_id))
        or 0
    )


def count_files_for_edition(db: Session, edition_id: str) -> int:
    table = _legacy_table(db, "LibraryFile")
    if table is None:
        return 0
    return int(
        db.scalar(select(func.count()).select_from(table).where(table.c.editionId == edition_id))
        or 0
    )


def count_editions_for_work(db: Session, work_id: str) -> int:
    table = _legacy_table(db, "LibraryEdition")
    if table is None:
        return 0
    return int(
        db.scalar(select(func.count()).select_from(table).where(table.c.workId == work_id))
        or 0
    )


def preferred_primary_edition_id(db: Session, work_id: str) -> str | None:
    table = _legacy_table(db, "LibraryEdition")
    if table is None:
        return None
    order_by = [table.c.createdAt, table.c.id]
    if "primary" in table.c:
        order_by = [func.coalesce(table.c.primary, False).desc(), *order_by]
    row = db.execute(
        select(table.c.id).where(table.c.workId == work_id).order_by(*order_by).limit(1)
    ).first()
    return str(row.id) if row is not None else None


def set_work_primary_edition(db: Session, *, work_id: str, primary_id: str) -> None:
    table = _legacy_table(db, "LibraryEdition")
    if table is None or "primary" not in table.c:
        return
    db.execute(update(table).where(table.c.workId == work_id).values(primary=False))
    db.execute(
        update(table)
        .where(table.c.id == primary_id, table.c.workId == work_id)
        .values(primary=True)
    )


def update_work_after_scope_delete(
    db: Session,
    *,
    work_id: str,
    primary_id: str | None,
    cover_path: str,
    cover_status: str,
    now: Any,
) -> None:
    db.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work_id)
        .values(
            primary_edition_id=primary_id,
            cover_path=cover_path,
            cover_status=cover_status,
            updated_at=now,
        )
    )
    db.flush()


def delete_edition_scope(db: Session, edition_id: str) -> int:
    """Delete one edition and its dependent rows. Returns deleted row count."""

    deleted_records = 0
    files = list_files_for_edition(db, edition_id)
    clear_file_references(db, [str(item["id"]) for item in files if item.get("id")])

    if _has_table(db, "ImportTask"):
        db.execute(
            update(ImportTask)
            .where(ImportTask.edition_id == edition_id)
            .values(edition_id=None, volume_id=None)
        )
    if _has_table(db, "KindleSendTask"):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.edition_id == edition_id)
            .values(edition_id=None, volume_id=None)
        )
    if _has_table(db, "LibraryConsumptionState"):
        db.execute(
            update(LibraryConsumptionState)
            .where(LibraryConsumptionState.last_edition_id == edition_id)
            .values(last_edition_id=None, last_volume_id=None, last_unit_id=None)
        )

    deleted_records += _delete_where(
        db, LibraryReadingProgress, LibraryReadingProgress.edition_id == edition_id
    )
    deleted_records += _delete_where(
        db, LibraryReadingUnit, LibraryReadingUnit.edition_id == edition_id
    )
    deleted_records += _delete_where(
        db, LibraryMetadata, LibraryMetadata.edition_id == edition_id
    )
    deleted_records += _delete_where(
        db, LibraryFile, LibraryFile.edition_id == edition_id
    )
    deleted_records += _delete_where(
        db, LibraryVolume, LibraryVolume.edition_id == edition_id
    )
    if _has_table(db, "LibraryEditionFacet"):
        library_operations.delete_edition_facets_for_edition(db, edition_id)
    deleted_records += _delete_where(
        db, LibraryEdition, LibraryEdition.id == edition_id
    )
    return deleted_records


def delete_volume_scope(db: Session, volume_id: str) -> int:
    """Delete one volume and its dependent rows. Returns deleted row count."""

    deleted_records = 0
    files = list_files_for_volume(db, volume_id)
    clear_file_references(db, [str(item["id"]) for item in files if item.get("id")])

    if _has_table(db, "ImportTask"):
        db.execute(
            update(ImportTask)
            .where(ImportTask.volume_id == volume_id)
            .values(volume_id=None)
        )
    if _has_table(db, "KindleSendTask"):
        db.execute(
            update(KindleSendTask)
            .where(KindleSendTask.volume_id == volume_id)
            .values(volume_id=None)
        )
    if _has_table(db, "LibraryConsumptionState"):
        db.execute(
            update(LibraryConsumptionState)
            .where(LibraryConsumptionState.last_volume_id == volume_id)
            .values(last_volume_id=None, last_unit_id=None)
        )

    deleted_records += _delete_where(
        db, LibraryReadingProgress, LibraryReadingProgress.volume_id == volume_id
    )
    deleted_records += _delete_where(
        db, LibraryReadingUnit, LibraryReadingUnit.volume_id == volume_id
    )
    deleted_records += _delete_where(
        db, LibraryFile, LibraryFile.volume_id == volume_id
    )
    deleted_records += _delete_where(
        db, LibraryVolume, LibraryVolume.id == volume_id
    )
    return deleted_records
