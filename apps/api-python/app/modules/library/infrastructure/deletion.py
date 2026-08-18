"""Volume-minimal cascade deletion for library resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.sql.base import Executable

from app.contracts.import_deletion import (
    LibraryVolumeDeletionResult,
    PreparedLibraryVolumeDeletion,
)
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
    LibraryVersion,
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
from app.modules.library.application.work_deletion import LibraryWorkDeletionStore
from app.modules.library.infrastructure.works import entity_as_legacy_dict


@dataclass(frozen=True)
class VolumeDeletionTarget:
    volume_id: str
    work_id: str
    cover_path: str | None


@dataclass(frozen=True, slots=True)
class PreparedVolumeScopeDeletion:
    volume_id: str
    before_volume_delete: tuple[Executable, ...]
    volume_delete: Executable
    after_volume_delete: tuple[Executable, ...]


def load_prepared_import_volume_deletion(
    db: Session,
    file_paths: tuple[str, ...],
    fallback_volume_id: str | None = None,
) -> PreparedLibraryVolumeDeletion | None:
    """Load the complete SQL decision projection without filesystem work."""

    target_statement = select(
        LibraryVolume.id.label("volume_id"),
        LibraryVolume.version_id.label("media_version_id"),
        LibraryVolume.cover_path.label("cover_path"),
        LibraryVersion.work_id.label("work_id"),
    ).select_from(LibraryVolume).join(
        LibraryVersion,
        LibraryVersion.id == LibraryVolume.version_id,
    )
    target_row = None
    if file_paths:
        path_order = case(
            {path: index for index, path in enumerate(file_paths)},
            value=LibraryFile.path,
            else_=len(file_paths),
        )
        target_row = db.execute(
            target_statement.join(
                LibraryFile, LibraryFile.volume_id == LibraryVolume.id
            )
            .where(LibraryFile.path.in_(file_paths))
            .order_by(path_order)
            .limit(1)
        ).one_or_none()
    if target_row is None and fallback_volume_id:
        target_row = db.execute(
            target_statement.where(LibraryVolume.id == fallback_volume_id)
        ).one_or_none()
    if target_row is None:
        return None
    volume_id = str(target_row.volume_id)
    media_version_id = str(target_row.media_version_id)
    work_id = str(target_row.work_id)
    file_rows = db.execute(
        select(LibraryFile.id, LibraryFile.path).where(
            LibraryFile.volume_id == volume_id
        )
    ).all()
    remaining_volume_count = int(
        db.scalar(
            select(func.count(LibraryVolume.id)).where(
                LibraryVolume.version_id == media_version_id,
                LibraryVolume.id != volume_id,
            )
        )
        or 0
    )
    delete_media_version = remaining_volume_count == 0
    remaining_media_count = int(
        db.scalar(
            select(func.count(LibraryVersion.id)).where(
                LibraryVersion.work_id == work_id,
                LibraryVersion.id != media_version_id,
            )
        )
        or 0
    )
    return PreparedLibraryVolumeDeletion(
        volume_id=volume_id,
        media_version_id=media_version_id,
        work_id=work_id,
        cover_path=(
            str(target_row.cover_path) if target_row.cover_path is not None else None
        ),
        file_ids=tuple(str(row.id) for row in file_rows),
        file_paths=tuple(str(row.path) for row in file_rows),
        delete_media_version=delete_media_version,
        delete_work=delete_media_version and remaining_media_count == 0,
    )


def find_volume_deletion_target_by_file_paths(
    db: Session, file_paths: list[str]
) -> VolumeDeletionTarget | None:
    """Resolve the first exact library-file path to its owning volume."""

    if not file_paths:
        return None
    rows = db.execute(
        select(
            LibraryFile.path,
            LibraryVolume.id.label("volume_id"),
            LibraryVolume.cover_path.label("cover_path"),
            LibraryVersion.work_id.label("work_id"),
        )
        .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(LibraryFile.path.in_(file_paths))
    ).all()
    targets_by_path = {
        str(row.path): VolumeDeletionTarget(
            volume_id=str(row.volume_id),
            work_id=str(row.work_id),
            cover_path=str(row.cover_path) if row.cover_path else None,
        )
        for row in rows
    }
    return next(
        (targets_by_path[path] for path in file_paths if path in targets_by_path),
        None,
    )


def find_volume_deletion_target_by_id(
    db: Session, volume_id: str
) -> VolumeDeletionTarget | None:
    row = db.execute(
        select(
            LibraryVolume.id.label("volume_id"),
            LibraryVolume.cover_path.label("cover_path"),
            LibraryVersion.work_id.label("work_id"),
        )
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(LibraryVolume.id == volume_id)
    ).one_or_none()
    if row is None:
        return None
    return VolumeDeletionTarget(
        volume_id=str(row.volume_id),
        work_id=str(row.work_id),
        cover_path=str(row.cover_path) if row.cover_path else None,
    )


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
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
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
    deleted = delete_work_records_bulk(db, (work_id,))
    return {"deleted": bool(deleted), "deletedDatabaseRecords": deleted}


def delete_work_records_bulk(db: Session, work_ids: tuple[str, ...]) -> int:
    if not work_ids:
        return 0
    media_version_ids = select(LibraryVersion.id).where(
        LibraryVersion.work_id.in_(work_ids)
    )
    volume_ids = select(LibraryVolume.id).where(
        LibraryVolume.version_id.in_(media_version_ids)
    )
    file_ids = select(LibraryFile.id).where(LibraryFile.volume_id.in_(volume_ids))
    statements = (
        update(ImportAsset)
        .where(ImportAsset.file_id.in_(file_ids))
        .values(file_id=None),
        update(KindleSendTask)
        .where(KindleSendTask.file_id.in_(file_ids))
        .values(file_id=None),
        update(ImportTask)
        .where(
            (ImportTask.work_id.in_(work_ids)) | ImportTask.volume_id.in_(volume_ids)
        )
        .values(work_id=None, volume_id=None),
        update(KindleSendTask)
        .where(
            (KindleSendTask.work_id.in_(work_ids))
            | KindleSendTask.volume_id.in_(volume_ids)
        )
        .values(work_id=None, volume_id=None, file_id=None),
        delete(BookConversionTask).where(
            (BookConversionTask.source_volume_id.in_(volume_ids))
            | (BookConversionTask.derived_volume_id.in_(volume_ids))
        ),
        delete(ReaderBookmark).where(ReaderBookmark.volume_id.in_(volume_ids)),
        delete(LibraryReadingProgress).where(
            LibraryReadingProgress.volume_id.in_(volume_ids)
        ),
        delete(LibraryReadingUnit).where(LibraryReadingUnit.volume_id.in_(volume_ids)),
        delete(LibraryMetadata).where(LibraryMetadata.volume_id.in_(volume_ids)),
        delete(LibraryVolumeFacet).where(LibraryVolumeFacet.volume_id.in_(volume_ids)),
        delete(LibraryFile).where(LibraryFile.volume_id.in_(volume_ids)),
        delete(UserMediaHistory).where(
            UserMediaHistory.media_version_id.in_(media_version_ids)
        ),
        delete(LibraryVolume).where(LibraryVolume.id.in_(volume_ids)),
        delete(LibraryMediaVersion).where(
            LibraryMediaVersion.id.in_(media_version_ids)
        ),
        delete(LibraryVersion).where(LibraryVersion.id.in_(media_version_ids)),
        delete(MetadataLookupTask).where(MetadataLookupTask.work_id.in_(work_ids)),
        delete(OrganizeJob).where(OrganizeJob.work_id.in_(work_ids)),
        delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id.in_(work_ids)),
        delete(ShelfWork).where(ShelfWork.work_id.in_(work_ids)),
        delete(WorkDetailPreference).where(WorkDetailPreference.work_id.in_(work_ids)),
    )
    for statement in statements:
        db.execute(statement)
    result = db.execute(delete(LibraryWork).where(LibraryWork.id.in_(work_ids)))
    return int(result.rowcount or 0)


class SqlAlchemyLibraryWorkDeletionStore(LibraryWorkDeletionStore):
    def __init__(self, db: Session) -> None:
        self._db = db

    def delete_records(self, work_ids: tuple[str, ...]) -> int:
        return delete_work_records_bulk(self._db, work_ids)


def prepare_delete_volume_scope(
    db: Session, volume_id: str
) -> PreparedVolumeScopeDeletion | None:
    projection = db.execute(
        select(
            LibraryVolume.version_id.label("media_version_id"),
            LibraryVersion.work_id,
        )
        .join(
            LibraryVersion,
            LibraryVersion.id == LibraryVolume.version_id,
        )
        .where(LibraryVolume.id == volume_id)
    ).one_or_none()
    if projection is None:
        return None
    media_version_id = str(projection.media_version_id)
    work_id = str(projection.work_id)
    file_ids = tuple(
        str(file_id)
        for file_id in db.scalars(
            select(LibraryFile.id).where(LibraryFile.volume_id == volume_id)
        ).all()
    )
    remaining_volume_count = int(
        db.scalar(
            select(func.count(LibraryVolume.id)).where(
                LibraryVolume.version_id == media_version_id,
                LibraryVolume.id != volume_id,
            )
        )
        or 0
    )
    delete_media_version = remaining_volume_count == 0
    remaining_media_count = int(
        db.scalar(
            select(func.count(LibraryVersion.id)).where(
                LibraryVersion.work_id == work_id,
                LibraryVersion.id != media_version_id,
            )
        )
        or 0
    )
    delete_work = delete_media_version and remaining_media_count == 0
    statements: list[Executable] = []
    if file_ids:
        statements.extend(
            (
                update(ImportAsset)
                .where(ImportAsset.file_id.in_(file_ids))
                .values(file_id=None),
                update(KindleSendTask)
                .where(KindleSendTask.file_id.in_(file_ids))
                .values(file_id=None),
            )
        )
    statements.extend(
        (
            update(ImportTask)
            .where(ImportTask.volume_id == volume_id)
            .values(volume_id=None),
            update(KindleSendTask)
            .where(KindleSendTask.volume_id == volume_id)
            .values(volume_id=None, file_id=None),
            update(MetadataLookupTask)
            .where(MetadataLookupTask.volume_id == volume_id)
            .values(volume_id=None),
            update(OrganizeJob)
            .where(OrganizeJob.volume_id == volume_id)
            .values(volume_id=None),
            update(LibraryVolume)
            .where(LibraryVolume.derived_from_volume_id == volume_id)
            .values(derived_from_volume_id=None),
            delete(BookConversionTask).where(
                BookConversionTask.source_volume_id == volume_id
            ),
            update(BookConversionTask)
            .where(BookConversionTask.derived_volume_id == volume_id)
            .values(derived_volume_id=None),
            delete(ReaderBookmark).where(ReaderBookmark.volume_id == volume_id),
            delete(LibraryReadingProgress).where(
                LibraryReadingProgress.volume_id == volume_id
            ),
            delete(LibraryReadingUnit).where(LibraryReadingUnit.volume_id == volume_id),
            delete(LibraryMetadata).where(LibraryMetadata.volume_id == volume_id),
            delete(LibraryVolumeFacet).where(LibraryVolumeFacet.volume_id == volume_id),
            delete(LibraryFile).where(LibraryFile.volume_id == volume_id),
        )
    )
    before_volume_delete = tuple(statements)
    volume_delete_statement = delete(LibraryVolume).where(LibraryVolume.id == volume_id)
    statements = []
    if delete_media_version:
        statements.extend(
            (
                delete(UserMediaHistory).where(
                    UserMediaHistory.media_version_id == media_version_id
                ),
                delete(LibraryMediaVersion).where(
                    LibraryMediaVersion.id == media_version_id
                ),
                delete(LibraryVersion).where(
                    LibraryVersion.id == media_version_id
                ),
            )
        )
    if delete_work:
        statements.extend(
            (
                update(ImportTask)
                .where(ImportTask.work_id == work_id)
                .values(work_id=None, volume_id=None),
                update(KindleSendTask)
                .where(KindleSendTask.work_id == work_id)
                .values(work_id=None, volume_id=None, file_id=None),
                delete(OrganizeJob).where(OrganizeJob.work_id == work_id),
                delete(MetadataLookupTask).where(MetadataLookupTask.work_id == work_id),
                delete(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work_id),
                delete(ShelfWork).where(ShelfWork.work_id == work_id),
                delete(WorkDetailPreference).where(
                    WorkDetailPreference.work_id == work_id
                ),
                delete(LibraryWork).where(LibraryWork.id == work_id),
            )
        )
    return PreparedVolumeScopeDeletion(
        volume_id=volume_id,
        before_volume_delete=before_volume_delete,
        volume_delete=volume_delete_statement,
        after_volume_delete=tuple(statements),
    )


def execute_prepared_volume_scope_deletion(
    db: Session, prepared: PreparedVolumeScopeDeletion
) -> int:
    for statement in prepared.before_volume_delete:
        db.execute(statement)
    result = db.execute(prepared.volume_delete)
    for statement in prepared.after_volume_delete:
        db.execute(statement)
    return int(result.rowcount or 0)


def _prepare_import_volume_deletion_statements(
    prepared: PreparedLibraryVolumeDeletion,
) -> PreparedVolumeScopeDeletion:
    before: list[Executable] = []
    if prepared.file_ids:
        before.extend(
            (
                update(ImportAsset)
                .where(ImportAsset.file_id.in_(prepared.file_ids))
                .values(file_id=None),
                update(KindleSendTask)
                .where(KindleSendTask.file_id.in_(prepared.file_ids))
                .values(file_id=None),
            )
        )
    before.extend(
        (
            update(ImportTask)
            .where(ImportTask.volume_id == prepared.volume_id)
            .values(volume_id=None),
            update(KindleSendTask)
            .where(KindleSendTask.volume_id == prepared.volume_id)
            .values(volume_id=None, file_id=None),
            update(MetadataLookupTask)
            .where(MetadataLookupTask.volume_id == prepared.volume_id)
            .values(volume_id=None),
            update(OrganizeJob)
            .where(OrganizeJob.volume_id == prepared.volume_id)
            .values(volume_id=None),
            update(LibraryVolume)
            .where(LibraryVolume.derived_from_volume_id == prepared.volume_id)
            .values(derived_from_volume_id=None),
            delete(BookConversionTask).where(
                BookConversionTask.source_volume_id == prepared.volume_id
            ),
            update(BookConversionTask)
            .where(BookConversionTask.derived_volume_id == prepared.volume_id)
            .values(derived_volume_id=None),
            delete(ReaderBookmark).where(
                ReaderBookmark.volume_id == prepared.volume_id
            ),
            delete(LibraryReadingProgress).where(
                LibraryReadingProgress.volume_id == prepared.volume_id
            ),
            delete(LibraryReadingUnit).where(
                LibraryReadingUnit.volume_id == prepared.volume_id
            ),
            delete(LibraryMetadata).where(
                LibraryMetadata.volume_id == prepared.volume_id
            ),
            delete(LibraryVolumeFacet).where(
                LibraryVolumeFacet.volume_id == prepared.volume_id
            ),
            delete(LibraryFile).where(
                LibraryFile.volume_id == prepared.volume_id
            ),
        )
    )
    after: list[Executable] = []
    if prepared.delete_media_version:
        after.extend(
            (
                delete(UserMediaHistory).where(
                    UserMediaHistory.media_version_id == prepared.media_version_id
                ),
                delete(LibraryMediaVersion).where(
                    LibraryMediaVersion.id == prepared.media_version_id
                ),
                delete(LibraryVersion).where(
                    LibraryVersion.id == prepared.media_version_id
                ),
            )
        )
    if prepared.delete_work:
        after.extend(
            (
                update(ImportTask)
                .where(ImportTask.work_id == prepared.work_id)
                .values(work_id=None, volume_id=None),
                update(KindleSendTask)
                .where(KindleSendTask.work_id == prepared.work_id)
                .values(work_id=None, volume_id=None, file_id=None),
                delete(OrganizeJob).where(OrganizeJob.work_id == prepared.work_id),
                delete(MetadataLookupTask).where(
                    MetadataLookupTask.work_id == prepared.work_id
                ),
                delete(LibraryWorkFacet).where(
                    LibraryWorkFacet.work_id == prepared.work_id
                ),
                delete(ShelfWork).where(ShelfWork.work_id == prepared.work_id),
                delete(WorkDetailPreference).where(
                    WorkDetailPreference.work_id == prepared.work_id
                ),
                delete(LibraryWork).where(LibraryWork.id == prepared.work_id),
            )
        )
    return PreparedVolumeScopeDeletion(
        volume_id=prepared.volume_id,
        before_volume_delete=tuple(before),
        volume_delete=delete(LibraryVolume).where(
            LibraryVolume.id == prepared.volume_id
        ),
        after_volume_delete=tuple(after),
    )


def execute_prepared_import_volume_deletion(
    db: Session,
    prepared: PreparedLibraryVolumeDeletion,
) -> LibraryVolumeDeletionResult:
    """Execute only statements derived from an already detached projection."""

    statements = _prepare_import_volume_deletion_statements(prepared)
    deleted = execute_prepared_volume_scope_deletion(db, statements) == 1
    return LibraryVolumeDeletionResult(
        deleted=deleted,
        deleted_work=deleted and prepared.delete_work,
        work_id=prepared.work_id,
    )


def delete_volume_scope(db: Session, volume_id: str) -> int:
    prepared = prepare_delete_volume_scope(db, volume_id)
    if prepared is None:
        return 0
    return execute_prepared_volume_scope_deletion(db, prepared)
