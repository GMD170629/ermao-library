"""Named ORM writes for import media persistence.

Replaces the transitional model-CRUD helper. Call sites pass
explicit column maps built at the application boundary; this adapter never owns
transactions.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.schema import Table
from sqlalchemy.sql.selectable import FromClause

from app.models.import_pipeline import ImportAsset, ImportLog, ImportTask
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryMetadata,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.models.organize import MetadataLookupTask, OrganizeJob
from app.modules.imports.infrastructure.source_keys import source_key


class SqlAlchemyLibraryImportStore:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _upsert_by_id(
        self, table: FromClause, columns: dict[str, object]
    ) -> dict[str, object]:
        """Idempotently persist one task-owned intermediate record."""

        concrete_table = cast(Table, table)
        statement = sqlite_insert(concrete_table).values(columns)
        update_values = {
            key: statement.excluded[key]
            for key in columns
            if key not in {"id", "createdAt"}
        }
        self._db.execute(
            statement.on_conflict_do_update(
                index_elements=[concrete_table.c.id],
                set_=update_values,
            )
        )
        return dict(columns)

    def insert_import_task(self, *, columns: dict[str, object]) -> dict[str, object]:
        self._db.execute(insert(ImportTask.__table__).values(columns))
        return dict(columns)

    def update_import_task(self, task_id: str, *, columns: dict[str, object]) -> None:
        if not columns:
            return
        self._db.execute(
            update(ImportTask.__table__).where(ImportTask.id == task_id).values(columns)
        )

    def insert_import_asset(self, *, columns: dict[str, object]) -> dict[str, object]:
        return self._upsert_by_id(ImportAsset.__table__, columns)

    def update_import_asset(self, asset_id: str, *, columns: dict[str, object]) -> None:
        self._db.execute(
            update(ImportAsset.__table__)
            .where(ImportAsset.id == asset_id)
            .values(columns)
        )

    def insert_import_log(self, *, columns: dict[str, object]) -> dict[str, object]:
        self._db.execute(insert(ImportLog.__table__).values(columns))
        return dict(columns)

    def insert_library_work(self, *, columns: dict[str, object]) -> dict[str, object]:
        allowed = {column.name for column in LibraryWork.__table__.columns}
        values = {key: value for key, value in columns.items() if key in allowed}
        return self._upsert_by_id(LibraryWork.__table__, values)

    def update_library_work(self, work_id: str, *, columns: dict[str, object]) -> None:
        allowed = {column.name for column in LibraryWork.__table__.columns}
        values = {key: value for key, value in columns.items() if key in allowed}
        self._db.execute(
            update(LibraryWork.__table__)
            .where(LibraryWork.id == work_id)
            .values(values)
        )

    def ensure_library_media_version(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        work_id = str(columns["workId"])
        media_kind = str(columns["mediaKind"])
        existing = (
            self._db.execute(
                select(LibraryMediaVersion.__table__).where(
                    LibraryMediaVersion.work_id == work_id,
                    LibraryMediaVersion.media_kind == media_kind,
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            return dict(existing)
        values: dict[str, object] = {
            key: columns[key]
            for key in ("id", "workId", "mediaKind", "createdAt", "updatedAt")
            if key in columns
        }
        self._db.execute(insert(LibraryMediaVersion.__table__).values(values))
        return dict(values)

    def update_library_media_version(
        self, media_version_id: str, *, columns: dict[str, object]
    ) -> None:
        allowed = {column.name for column in LibraryMediaVersion.__table__.columns}
        values = {key: value for key, value in columns.items() if key in allowed}
        if values:
            self._db.execute(
                update(LibraryMediaVersion.__table__)
                .where(LibraryMediaVersion.id == media_version_id)
                .values(values)
            )

    def delete_library_media_version_if_empty(self, media_version_id: str) -> None:
        volume_count = self._db.scalar(
            select(func.count(LibraryVolume.id)).where(
                LibraryVolume.media_version_id == media_version_id
            )
        )
        if int(volume_count or 0) == 0:
            self._db.execute(
                delete(LibraryMediaVersion).where(
                    LibraryMediaVersion.id == media_version_id
                )
            )

    def insert_library_volume(self, *, columns: dict[str, object]) -> dict[str, object]:
        media_version_id = str(columns.get("mediaVersionId") or "")
        if not media_version_id:
            raise ValueError("LibraryVolume.mediaVersionId is required")
        if not columns.get("format"):
            raise ValueError("LibraryVolume.format is required")
        if not columns.get("resourceKey"):
            raise ValueError("LibraryVolume.resourceKey is required")
        normalized = {**columns, "mediaVersionId": media_version_id}
        allowed = {column.name for column in LibraryVolume.__table__.columns}
        normalized = {key: value for key, value in normalized.items() if key in allowed}
        existing_status = self._db.scalar(
            select(LibraryVolume.import_status).where(
                LibraryVolume.id == str(normalized["id"])
            )
        )
        if existing_status is not None and str(existing_status) not in {
            "COMPLETED",
            "IMPORTED",
            "READY",
        }:
            self._db.execute(
                delete(LibraryMetadata).where(
                    LibraryMetadata.volume_id == str(normalized["id"])
                )
            )
        return self._upsert_by_id(LibraryVolume.__table__, normalized)

    def update_library_volume(
        self, volume_id: str, *, columns: dict[str, object]
    ) -> None:
        self._db.execute(
            update(LibraryVolume.__table__)
            .where(LibraryVolume.id == volume_id)
            .values(columns)
        )

    def insert_library_file(self, *, columns: dict[str, object]) -> dict[str, object]:
        path = columns.get("path")
        if isinstance(path, str):
            columns = {**columns, "pathKey": source_key(path)}
            existing = (
                self._db.execute(
                    select(
                        LibraryFile.id,
                        LibraryFile.volume_id,
                        LibraryVolume.import_status,
                    )
                    .join(LibraryVolume, LibraryVolume.id == LibraryFile.volume_id)
                    .where(LibraryFile.path == path)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if existing is not None and str(existing["import_status"]) not in {
                "COMPLETED",
                "IMPORTED",
                "READY",
            }:
                existing_id = str(existing["id"])
                self._db.execute(
                    delete(LibraryReadingUnit).where(
                        LibraryReadingUnit.file_id == existing_id
                    )
                )
                values = {
                    key: value
                    for key, value in columns.items()
                    if key not in {"id", "createdAt"}
                }
                self._db.execute(
                    update(LibraryFile.__table__)
                    .where(LibraryFile.__table__.c.id == existing_id)
                    .values(values)
                )
                return {**columns, "id": existing_id}
        return self._upsert_by_id(LibraryFile.__table__, columns)

    def update_library_file(self, file_id: str, *, columns: dict[str, object]) -> None:
        path = columns.get("path")
        if isinstance(path, str):
            columns = {**columns, "pathKey": source_key(path)}
        self._db.execute(
            update(LibraryFile.__table__)
            .where(LibraryFile.id == file_id)
            .values(columns)
        )

    def get_library_file(self, file_id: str) -> dict[str, object] | None:
        row = (
            self._db.execute(
                select(LibraryFile.__table__).where(LibraryFile.id == file_id)
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def insert_library_reading_unit(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        return self._upsert_by_id(LibraryReadingUnit.__table__, columns)

    def update_library_reading_unit(
        self, unit_id: str, *, columns: dict[str, object]
    ) -> None:
        self._db.execute(
            update(LibraryReadingUnit.__table__)
            .where(LibraryReadingUnit.id == unit_id)
            .values(columns)
        )

    def get_library_reading_unit(self, unit_id: str) -> dict[str, object] | None:
        row = (
            self._db.execute(
                select(LibraryReadingUnit.__table__).where(
                    LibraryReadingUnit.id == unit_id
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def delete_library_reading_unit(self, unit_id: str) -> None:
        self._db.execute(
            delete(LibraryReadingUnit).where(LibraryReadingUnit.id == unit_id)
        )

    def insert_library_metadata(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        if not columns.get("volumeId"):
            raise ValueError("LibraryMetadata.volumeId is required")
        return self._upsert_by_id(LibraryMetadata.__table__, columns)

    def update_library_reading_progress(
        self,
        progress_id: str,
        *,
        columns: dict[str, object],
    ) -> None:
        self._db.execute(
            update(LibraryReadingProgress.__table__)
            .where(LibraryReadingProgress.id == progress_id)
            .values(columns)
        )

    def update_user_media_history(
        self,
        history_id: str,
        *,
        columns: dict[str, object],
    ) -> None:
        self._db.execute(
            update(UserMediaHistory.__table__)
            .where(UserMediaHistory.id == history_id)
            .values(columns)
        )

    def insert_organize_job(self, *, columns: dict[str, object]) -> dict[str, object]:
        self._db.execute(insert(OrganizeJob.__table__).values(columns))
        return dict(columns)

    def update_organize_job(self, job_id: str, *, columns: dict[str, object]) -> None:
        self._db.execute(
            update(OrganizeJob.__table__)
            .where(OrganizeJob.id == job_id)
            .values(columns)
        )

    def insert_metadata_lookup_task(
        self, *, columns: dict[str, object]
    ) -> dict[str, object]:
        self._db.execute(insert(MetadataLookupTask.__table__).values(columns))
        return dict(columns)

    def update_metadata_lookup_task(
        self, task_id: str, *, columns: dict[str, object]
    ) -> None:
        self._db.execute(
            update(MetadataLookupTask.__table__)
            .where(MetadataLookupTask.id == task_id)
            .values(columns)
        )
