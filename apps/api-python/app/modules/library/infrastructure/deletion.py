"""Volume-minimal cascade deletion for library resources."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.auth import ReaderBookmark
from app.models.import_pipeline import (
    BookConversionTask,
    ImportAsset,
    ImportTask,
    KindleSendTask,
)
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryVolumeFacet,
    LibraryWork,
    LibraryWorkFacet,
    UserMediaHistory,
    WorkDetailPreference,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.models.shelf import ShelfWork
from app.modules.library.infrastructure.works import entity_as_legacy_dict


def clear_file_references(db: Session, file_ids: list[str]) -> None:
    if not file_ids:
        return
    db.execute(
        update(ImportAsset)
        .where(ImportAsset.file_id.in_(file_ids))
        .values(file_id=None)
    )
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.file_id.in_(file_ids))
        .values(file_id=None)
    )


def list_files_for_volume(db: Session, volume_id: str) -> list[dict[str, Any]]:
    files = db.scalars(
        select(LibraryFile).where(LibraryFile.volume_id == volume_id)
    ).all()
    return [entity_as_legacy_dict(file) for file in files]


def get_volume_for_work(
    db: Session, *, volume_id: str, work_id: str
) -> dict[str, Any] | None:
    volume = db.scalar(
        select(LibraryVolume)
        .join(
            LibraryMediaVersion,
            LibraryMediaVersion.id == LibraryVolume.media_version_id,
        )
        .where(
            LibraryVolume.id == volume_id,
            LibraryMediaVersion.work_id == work_id,
        )
    )
    return entity_as_legacy_dict(volume) if volume is not None else None


def work_exists(db: Session, work_id: str) -> bool:
    return db.get(LibraryWork, work_id) is not None


def delete_work_records(db: Session, work_id: str) -> dict[str, Any]:
    media_version_ids = select(LibraryMediaVersion.id).where(
        LibraryMediaVersion.work_id == work_id
    )
    volume_ids = select(LibraryVolume.id).where(
        LibraryVolume.media_version_id.in_(media_version_ids)
    )
    file_ids = list(
        db.scalars(select(LibraryFile.id).where(LibraryFile.volume_id.in_(volume_ids)))
    )
    clear_file_references(db, [str(file_id) for file_id in file_ids])
    db.execute(
        update(ImportTask)
        .where((ImportTask.work_id == work_id) | ImportTask.volume_id.in_(volume_ids))
        .values(work_id=None, volume_id=None)
    )
    db.execute(
        update(KindleSendTask)
        .where(
            (KindleSendTask.work_id == work_id)
            | KindleSendTask.volume_id.in_(volume_ids)
        )
        .values(work_id=None, volume_id=None, file_id=None)
    )
    db.execute(
        update(MetadataLookupTask)
        .where(MetadataLookupTask.work_id == work_id)
        .values(volume_id=None)
    )
    db.execute(
        update(OrganizeJob).where(OrganizeJob.work_id == work_id).values(volume_id=None)
    )
    db.execute(
        delete(BookConversionTask).where(
            (BookConversionTask.source_volume_id.in_(volume_ids))
            | (BookConversionTask.derived_volume_id.in_(volume_ids))
        )
    )
    db.execute(delete(ReaderBookmark).where(ReaderBookmark.volume_id.in_(volume_ids)))
    db.execute(
        delete(LibraryReadingProgress).where(
            LibraryReadingProgress.volume_id.in_(volume_ids)
        )
    )
    db.execute(
        delete(LibraryReadingUnit).where(LibraryReadingUnit.volume_id.in_(volume_ids))
    )
    db.execute(delete(LibraryMetadata).where(LibraryMetadata.volume_id.in_(volume_ids)))
    db.execute(
        delete(LibraryVolumeFacet).where(LibraryVolumeFacet.volume_id.in_(volume_ids))
    )
    db.execute(delete(LibraryFile).where(LibraryFile.volume_id.in_(volume_ids)))
    db.execute(
        delete(UserMediaHistory).where(
            UserMediaHistory.media_version_id.in_(media_version_ids)
        )
    )
    db.execute(delete(LibraryVolume).where(LibraryVolume.id.in_(volume_ids)))
    db.execute(
        delete(LibraryMediaVersion).where(LibraryMediaVersion.id.in_(media_version_ids))
    )
    db.execute(delete(MetadataLookupTask).where(MetadataLookupTask.work_id == work_id))
    db.execute(delete(OrganizeJob).where(OrganizeJob.work_id == work_id))
    db.execute(delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id))
    db.execute(delete(ShelfWork).where(ShelfWork.work_id == work_id))
    db.execute(
        delete(WorkDetailPreference).where(WorkDetailPreference.work_id == work_id)
    )
    result = db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))
    db.flush()
    return {
        "deleted": bool(result.rowcount),
        "deletedDatabaseRecords": int(result.rowcount or 0),
    }


def delete_volume_scope(db: Session, volume_id: str) -> int:
    volume = db.get(LibraryVolume, volume_id)
    if volume is None:
        return 0
    media_version = db.get(LibraryMediaVersion, volume.media_version_id)
    work_id = media_version.work_id if media_version is not None else None
    files = list_files_for_volume(db, volume_id)
    clear_file_references(db, [str(file["id"]) for file in files if file.get("id")])
    db.execute(
        update(ImportTask)
        .where(ImportTask.volume_id == volume_id)
        .values(volume_id=None)
    )
    db.execute(
        update(KindleSendTask)
        .where(KindleSendTask.volume_id == volume_id)
        .values(volume_id=None, file_id=None)
    )
    db.execute(
        update(MetadataLookupTask)
        .where(MetadataLookupTask.volume_id == volume_id)
        .values(volume_id=None)
    )
    db.execute(
        update(OrganizeJob)
        .where(OrganizeJob.volume_id == volume_id)
        .values(volume_id=None)
    )
    db.execute(
        update(LibraryVolume)
        .where(LibraryVolume.derived_from_volume_id == volume_id)
        .values(derived_from_volume_id=None)
    )
    db.execute(
        delete(BookConversionTask).where(
            BookConversionTask.source_volume_id == volume_id
        )
    )
    db.execute(
        update(BookConversionTask)
        .where(BookConversionTask.derived_volume_id == volume_id)
        .values(derived_volume_id=None)
    )
    db.execute(delete(ReaderBookmark).where(ReaderBookmark.volume_id == volume_id))
    db.execute(
        delete(LibraryReadingProgress).where(
            LibraryReadingProgress.volume_id == volume_id
        )
    )
    db.execute(
        delete(LibraryReadingUnit).where(LibraryReadingUnit.volume_id == volume_id)
    )
    db.execute(delete(LibraryMetadata).where(LibraryMetadata.volume_id == volume_id))
    db.execute(
        delete(LibraryVolumeFacet).where(LibraryVolumeFacet.volume_id == volume_id)
    )
    db.execute(delete(LibraryFile).where(LibraryFile.volume_id == volume_id))
    result = db.execute(delete(LibraryVolume).where(LibraryVolume.id == volume_id))
    if media_version is not None:
        remaining = int(
            db.scalar(
                select(func.count(LibraryVolume.id)).where(
                    LibraryVolume.media_version_id == media_version.id
                )
            )
            or 0
        )
        if remaining == 0:
            db.execute(
                delete(UserMediaHistory).where(
                    UserMediaHistory.media_version_id == media_version.id
                )
            )
            db.execute(
                delete(LibraryMediaVersion).where(
                    LibraryMediaVersion.id == media_version.id
                )
            )
    if work_id is not None:
        remaining_media = int(
            db.scalar(
                select(func.count(LibraryMediaVersion.id)).where(
                    LibraryMediaVersion.work_id == work_id
                )
            )
            or 0
        )
        if remaining_media == 0:
            db.execute(
                update(ImportTask)
                .where(ImportTask.work_id == work_id)
                .values(work_id=None, volume_id=None)
            )
            db.execute(
                update(KindleSendTask)
                .where(KindleSendTask.work_id == work_id)
                .values(work_id=None, volume_id=None, file_id=None)
            )
            db.execute(delete(OrganizeJob).where(OrganizeJob.work_id == work_id))
            db.execute(
                delete(MetadataLookupTask).where(MetadataLookupTask.work_id == work_id)
            )
            db.execute(
                delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id)
            )
            db.execute(delete(ShelfWork).where(ShelfWork.work_id == work_id))
            db.execute(
                delete(WorkDetailPreference).where(
                    WorkDetailPreference.work_id == work_id
                )
            )
            db.execute(delete(LibraryWork).where(LibraryWork.id == work_id))
    db.flush()
    return int(result.rowcount or 0)
