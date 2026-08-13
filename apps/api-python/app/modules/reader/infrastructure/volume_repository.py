"""SQLAlchemy ORM adapter for volume-scoped reader resources."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import case, delete, false, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.contracts.epub_navigation import (
    EPUB_HREF_BASE_METADATA_KEY,
    EPUB_PUBLICATION_ROOT_HREF_BASE,
)
from app.core.sql_batches import sqlite_parameter_chunks
from app.models.auth import ReaderBookmark
from app.models.common import cuid
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    ReaderProgressMutation,
    UserMediaHistory,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderEpubSourceDto,
    ReaderFileDto,
    ReaderMediaVersionDto,
    ReaderProgressDto,
    ReaderReadingStatus,
    ReaderRecoveredEpubChapterDto,
    ReaderUnitDto,
    ReaderVolumeContextDto,
    ReaderVolumeDto,
    ReaderWorkDto,
)


def _volume_dto(volume: LibraryVolume) -> ReaderVolumeDto:
    return ReaderVolumeDto(
        id=volume.id,
        media_version_id=volume.media_version_id,
        title=volume.title,
        volume_index=volume.volume_index,
        sort_order=volume.sort_order,
        format=volume.format,
        derived_from_volume_id=volume.derived_from_volume_id,
        page_count=volume.page_count,
        chapter_count=volume.chapter_count,
        duration_ms=volume.duration_ms,
        track_count=volume.track_count,
        updated_at=volume.updated_at,
    )


def _progress_dto(progress: LibraryReadingProgress) -> ReaderProgressDto:
    return ReaderProgressDto(
        id=progress.id,
        user_id=progress.user_id,
        volume_id=progress.volume_id,
        reader_type=progress.reader_type,
        percent=progress.percent,
        location_json=progress.location_json,
        content_fingerprint=progress.content_fingerprint,
        mutation_id=progress.mutation_id,
        client_id=progress.client_id,
        client_sequence=progress.client_sequence,
        progressed_at=progress.progressed_at,
        source_protocol=progress.source_protocol,
        source_device_name=progress.source_device_name,
        updated_at=progress.updated_at,
        revision=progress.revision,
    )


def _mutation_progress_dto(mutation: ReaderProgressMutation) -> ReaderProgressDto:
    return ReaderProgressDto(
        id=mutation.id,
        user_id=mutation.user_id,
        volume_id=mutation.volume_id,
        reader_type="readium",
        percent=mutation.display_percent,
        location_json=mutation.locator_json,
        content_fingerprint=mutation.content_fingerprint,
        mutation_id=mutation.mutation_id,
        client_id=mutation.client_id,
        client_sequence=None,
        progressed_at=mutation.captured_at,
        source_protocol="SHUKU_READER_V4",
        source_device_name=None,
        updated_at=mutation.received_at,
        revision=mutation.revision,
    )


def _legacy_bookmark_datetime(value: str, fallback: datetime) -> datetime:
    normalized = value.strip()
    if normalized:
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            try:
                timestamp = float(normalized)
                if abs(timestamp) >= 10_000_000_000:
                    timestamp /= 1000
                return datetime.fromtimestamp(timestamp, tz=UTC)
            except (OSError, OverflowError, ValueError):
                pass
    return fallback if fallback.tzinfo is not None else fallback.replace(tzinfo=UTC)


def _bookmark_dto(bookmark: ReaderBookmark) -> ReaderBookmarkDto:
    return ReaderBookmarkDto(
        id=bookmark.id,
        bookmark_id=bookmark.bookmark_id,
        location_json=bookmark.location_json,
        label=bookmark.label,
        percent=bookmark.percent,
        bookmark_created_at=_legacy_bookmark_datetime(
            bookmark.bookmark_created_at,
            bookmark.created_at,
        ),
    )


def _epub_navigation_metadata(
    existing_metadata_json: str | None,
    idref: str | None,
) -> str:
    metadata: dict[str, object] = {}
    if existing_metadata_json:
        try:
            loaded: object = json.loads(existing_metadata_json)
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            metadata = {str(key): value for key, value in loaded.items()}
    metadata.update(
        {
            "idref": idref,
            "recovered": True,
            EPUB_HREF_BASE_METADATA_KEY: EPUB_PUBLICATION_ROOT_HREF_BASE,
        }
    )
    return json.dumps(metadata, ensure_ascii=False)


class SqlAlchemyReaderVolumeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_context(self, volume_id: str) -> ReaderVolumeContextDto | None:
        row = self._session.execute(
            select(LibraryWork, LibraryMediaVersion, LibraryVolume)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.work_id == LibraryWork.id,
            )
            .join(
                LibraryVolume,
                LibraryVolume.media_version_id == LibraryMediaVersion.id,
            )
            .where(LibraryVolume.id == volume_id, LibraryVolume.hidden.is_(False))
        ).one_or_none()
        if row is None:
            return None
        work, media_version, volume = row
        return ReaderVolumeContextDto(
            work=ReaderWorkDto(id=work.id, title=work.title, author=work.author),
            media_version=ReaderMediaVersionDto(
                id=media_version.id,
                work_id=media_version.work_id,
                media_kind=media_version.media_kind,
            ),
            volume=_volume_dto(volume),
        )

    def list_visible_volumes_for_work(
        self, work_id: str, access_scope: ReaderAccessScope
    ) -> list[ReaderVolumeDto]:
        visibility: ColumnElement[bool] = LibraryVolume.id.is_not(None)
        if not access_scope.is_admin:
            clauses = []
            if access_scope.monitor_folder_ids:
                clauses.append(
                    LibraryVolume.monitor_folder_id.in_(access_scope.monitor_folder_ids)
                )
            if access_scope.can_view_manual_imports:
                clauses.append(LibraryVolume.monitor_folder_id.is_(None))
            visibility = or_(*clauses) if clauses else false()
        volumes = self._session.scalars(
            select(LibraryVolume)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(
                LibraryMediaVersion.work_id == work_id,
                LibraryVolume.hidden.is_(False),
                visibility,
            )
            .order_by(
                case(
                    (LibraryMediaVersion.media_kind == "EBOOK", 0),
                    (LibraryMediaVersion.media_kind == "COMIC", 1),
                    (LibraryMediaVersion.media_kind == "AUDIOBOOK", 2),
                    else_=3,
                ),
                LibraryVolume.sort_order,
                LibraryVolume.created_at,
                LibraryVolume.id,
            )
        ).all()
        return [_volume_dto(volume) for volume in volumes]

    def list_files(self, volume_id: str) -> list[ReaderFileDto]:
        files = self._session.scalars(
            select(LibraryFile)
            .where(LibraryFile.volume_id == volume_id)
            .order_by(LibraryFile.sort_order, LibraryFile.created_at, LibraryFile.id)
        ).all()
        return [
            ReaderFileDto(
                id=file.id,
                volume_id=file.volume_id,
                kind=file.kind,
                mime_type=file.mime_type,
                size_bytes=file.size_bytes,
                duration_ms=file.duration_ms,
                disc_number=file.disc_number,
                track_number=file.track_number,
                sort_order=file.sort_order,
                fingerprint=file.fingerprint,
                full_hash=file.full_hash,
                mtime_ms=file.mtime_ms,
                codec=file.codec,
            )
            for file in files
        ]

    def list_units(self, volume_id: str) -> list[ReaderUnitDto]:
        units = self._session.scalars(
            select(LibraryReadingUnit)
            .where(LibraryReadingUnit.volume_id == volume_id)
            .order_by(LibraryReadingUnit.sort_order, LibraryReadingUnit.id)
        ).all()
        return [
            ReaderUnitDto(
                id=unit.id,
                volume_id=unit.volume_id,
                file_id=unit.file_id,
                unit_type=unit.unit_type,
                title=unit.title,
                href=unit.href,
                media_type=unit.media_type,
                sort_order=unit.sort_order,
                start_ms=unit.start_ms,
                end_ms=unit.end_ms,
                duration_ms=unit.duration_ms,
                metadata_json=unit.metadata_json,
            )
            for unit in units
        ]

    def get_epub_source(self, volume_id: str) -> ReaderEpubSourceDto | None:
        source = self._session.scalar(
            select(LibraryFile)
            .where(
                LibraryFile.volume_id == volume_id,
                LibraryFile.kind == "EPUB",
            )
            .order_by(LibraryFile.sort_order, LibraryFile.created_at, LibraryFile.id)
        )
        return (
            ReaderEpubSourceDto(file_id=source.id, path=source.path)
            if source is not None
            else None
        )

    def epub_navigation_needs_repair(self, volume_id: str) -> bool:
        metadata_values = self._session.scalars(
            select(LibraryReadingUnit.metadata_json).where(
                LibraryReadingUnit.volume_id == volume_id,
                LibraryReadingUnit.unit_type == "chapter",
            )
        ).all()
        if not metadata_values:
            return True
        for metadata_json in metadata_values:
            try:
                metadata = json.loads(metadata_json)
            except (TypeError, json.JSONDecodeError):
                return True
            if not isinstance(metadata, dict) or (
                metadata.get(EPUB_HREF_BASE_METADATA_KEY)
                != EPUB_PUBLICATION_ROOT_HREF_BASE
            ):
                return True
        return False

    def replace_epub_navigation_units(
        self,
        *,
        volume_id: str,
        file_id: str,
        chapters: tuple[ReaderRecoveredEpubChapterDto, ...],
        now: datetime,
    ) -> None:
        existing_units = {
            unit.sort_order: unit
            for unit in self._session.scalars(
                select(LibraryReadingUnit).where(
                    LibraryReadingUnit.volume_id == volume_id,
                    LibraryReadingUnit.unit_type == "chapter",
                )
            ).all()
        }
        recovered_sort_orders = {chapter.sort_order for chapter in chapters}
        rows: list[dict[str, object]] = []
        for chapter in chapters:
            existing = existing_units.get(chapter.sort_order)
            metadata = _epub_navigation_metadata(
                existing.metadata_json if existing is not None else None,
                chapter.idref,
            )
            digest = hashlib.sha256(
                f"{volume_id}\0{chapter.sort_order}\0{chapter.href}".encode()
            ).hexdigest()[:32]
            rows.append(
                {
                    "id": existing.id
                    if existing is not None
                    else f"recovered_{digest}",
                    "volumeId": volume_id,
                    "fileId": file_id,
                    "unitType": "chapter",
                    "title": chapter.title,
                    "href": chapter.href,
                    "mediaType": chapter.media_type,
                    "sortOrder": chapter.sort_order,
                    "metadataJson": metadata,
                    "createdAt": now,
                    "updatedAt": now,
                }
            )
        for chunk in sqlite_parameter_chunks(rows, parameters_per_row=11):
            insert_statement = sqlite_insert(LibraryReadingUnit).values(list(chunk))
            self._session.execute(
                insert_statement.on_conflict_do_update(
                    index_elements=["volumeId", "unitType", "sortOrder"],
                    set_={
                        "fileId": insert_statement.excluded["fileId"],
                        "title": insert_statement.excluded.title,
                        "href": insert_statement.excluded.href,
                        "mediaType": insert_statement.excluded["mediaType"],
                        "metadataJson": insert_statement.excluded["metadataJson"],
                        "updatedAt": insert_statement.excluded["updatedAt"],
                    },
                )
            )
        stale_units = delete(LibraryReadingUnit).where(
            LibraryReadingUnit.volume_id == volume_id,
            LibraryReadingUnit.unit_type == "chapter",
        )
        if recovered_sort_orders:
            stale_units = stale_units.where(
                LibraryReadingUnit.sort_order.not_in(recovered_sort_orders)
            )
        self._session.execute(stale_units)
        self._session.execute(
            update(LibraryVolume)
            .where(LibraryVolume.id == volume_id)
            .values(chapter_count=len(chapters), updated_at=now)
        )

    def get_progress(self, user_id: str, volume_id: str) -> ReaderProgressDto | None:
        progress = self._session.scalar(
            select(LibraryReadingProgress).where(
                LibraryReadingProgress.user_id == user_id,
                LibraryReadingProgress.volume_id == volume_id,
            )
        )
        return _progress_dto(progress) if progress else None

    def list_progresses(
        self, user_id: str, volume_ids: list[str]
    ) -> list[ReaderProgressDto]:
        if not volume_ids:
            return []
        progresses = self._session.scalars(
            select(LibraryReadingProgress).where(
                LibraryReadingProgress.user_id == user_id,
                LibraryReadingProgress.volume_id.in_(volume_ids),
            )
        ).all()
        return [_progress_dto(progress) for progress in progresses]

    def get_progress_mutation(
        self, user_id: str, volume_id: str, mutation_id: str
    ) -> ReaderProgressDto | None:
        mutation = self._session.scalar(
            select(ReaderProgressMutation).where(
                ReaderProgressMutation.user_id == user_id,
                ReaderProgressMutation.volume_id == volume_id,
                ReaderProgressMutation.mutation_id == mutation_id,
            )
        )
        return _mutation_progress_dto(mutation) if mutation is not None else None

    def save_exact_progress(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        display_percent: float,
        locator_json: str,
        content_fingerprint: str,
        client_id: str,
        mutation_id: str,
        base_revision: int,
        next_revision: int,
        progressed_at: datetime,
        now: datetime,
    ) -> ReaderProgressDto | None:
        if base_revision == 0:
            insert_statement = sqlite_insert(LibraryReadingProgress).values(
                id=cuid(),
                userId=user_id,
                volumeId=context.volume.id,
                readerType=reader_type,
                position="0",
                page=None,
                percent=display_percent,
                extra="{}",
                schemaVersion=4,
                locationType="readium",
                locationJson=locator_json,
                contentFingerprint=content_fingerprint,
                mutationId=mutation_id,
                clientId=client_id,
                clientSequence=None,
                progressedAt=progressed_at,
                sourceProtocol="SHUKU_READER_V4",
                sourceDeviceName=None,
                createdAt=now,
                updatedAt=now,
                revision=next_revision,
            )
            progress = self._session.scalar(
                insert_statement.on_conflict_do_nothing(
                    index_elements=[
                        LibraryReadingProgress.user_id,
                        LibraryReadingProgress.volume_id,
                    ]
                ).returning(LibraryReadingProgress)
            )
        else:
            progress = self._session.scalar(
                update(LibraryReadingProgress)
                .where(
                    LibraryReadingProgress.user_id == user_id,
                    LibraryReadingProgress.volume_id == context.volume.id,
                    LibraryReadingProgress.revision == base_revision,
                )
                .values(
                    reader_type=reader_type,
                    percent=display_percent,
                    schema_version=4,
                    location_type="readium",
                    location_json=locator_json,
                    content_fingerprint=content_fingerprint,
                    mutation_id=mutation_id,
                    client_id=client_id,
                    client_sequence=None,
                    progressed_at=progressed_at,
                    source_protocol="SHUKU_READER_V4",
                    source_device_name=None,
                    updated_at=now,
                    revision=next_revision,
                )
                .returning(LibraryReadingProgress)
                .execution_options(populate_existing=True)
            )
        if progress is None:
            return None

        self._session.add(
            ReaderProgressMutation(
                user_id=user_id,
                volume_id=context.volume.id,
                mutation_id=mutation_id,
                client_id=client_id,
                revision=next_revision,
                locator_json=locator_json,
                content_fingerprint=content_fingerprint,
                display_percent=display_percent,
                captured_at=progressed_at,
                received_at=now,
            )
        )
        self._session.execute(
            delete(ReaderProgressMutation).where(
                ReaderProgressMutation.user_id == user_id,
                ReaderProgressMutation.volume_id == context.volume.id,
                ReaderProgressMutation.revision <= next_revision - 32,
            )
        )

        history_insert = sqlite_insert(UserMediaHistory).values(
            id=cuid(),
            userId=user_id,
            mediaVersionId=context.media_version.id,
            lastVolumeId=context.volume.id,
            createdAt=now,
            updatedAt=now,
        )
        self._session.execute(
            history_insert.on_conflict_do_update(
                index_elements=[
                    UserMediaHistory.user_id,
                    UserMediaHistory.media_version_id,
                ],
                set_={
                    "lastVolumeId": history_insert.excluded["lastVolumeId"],
                    "updatedAt": history_insert.excluded["updatedAt"],
                },
            )
        )
        return _progress_dto(progress)

    def set_reading_status(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        status: ReaderReadingStatus,
        content_fingerprint: str,
        now: datetime,
    ) -> ReaderProgressDto | None:
        if status == "UNREAD":
            self._session.execute(
                delete(LibraryReadingProgress).where(
                    LibraryReadingProgress.user_id == user_id,
                    LibraryReadingProgress.volume_id == context.volume.id,
                )
            )
            self._session.execute(
                delete(ReaderProgressMutation).where(
                    ReaderProgressMutation.user_id == user_id,
                    ReaderProgressMutation.volume_id == context.volume.id,
                )
            )
            return None

        progress_insert = sqlite_insert(LibraryReadingProgress).values(
            id=cuid(),
            userId=user_id,
            volumeId=context.volume.id,
            readerType=reader_type,
            position="0",
            page=None,
            percent=100,
            extra="{}",
            schemaVersion=4,
            locationType=None,
            locationJson=None,
            contentFingerprint=content_fingerprint,
            mutationId=None,
            clientId="shuku-library",
            clientSequence=None,
            progressedAt=now,
            sourceProtocol="SHUKU_READER_V4",
            sourceDeviceName=None,
            createdAt=now,
            updatedAt=now,
        )
        progress = self._session.scalar(
            progress_insert.on_conflict_do_update(
                index_elements=[
                    LibraryReadingProgress.user_id,
                    LibraryReadingProgress.volume_id,
                ],
                set_={
                    "readerType": progress_insert.excluded["readerType"],
                    "percent": progress_insert.excluded.percent,
                    "schemaVersion": progress_insert.excluded["schemaVersion"],
                    "updatedAt": progress_insert.excluded["updatedAt"],
                },
            )
            .returning(LibraryReadingProgress)
            .execution_options(populate_existing=True)
        )
        if progress is None:
            raise RuntimeError("reading status upsert returned no row")
        history_insert = sqlite_insert(UserMediaHistory).values(
            id=cuid(),
            userId=user_id,
            mediaVersionId=context.media_version.id,
            lastVolumeId=context.volume.id,
            createdAt=now,
            updatedAt=now,
        )
        self._session.execute(
            history_insert.on_conflict_do_update(
                index_elements=[
                    UserMediaHistory.user_id,
                    UserMediaHistory.media_version_id,
                ],
                set_={
                    "lastVolumeId": context.volume.id,
                    "updatedAt": now,
                },
            )
        )
        return _progress_dto(progress)

    def save_external_progress(
        self,
        *,
        user_id: str,
        context: ReaderVolumeContextDto,
        reader_type: str,
        percent: float,
        location_json: str,
        content_fingerprint: str,
        mutation_id: str,
        client_id: str,
        client_sequence: int,
        progressed_at: datetime,
        source_protocol: str,
        source_device_name: str,
        now: datetime,
    ) -> ReaderProgressDto:
        progress_insert = sqlite_insert(LibraryReadingProgress).values(
            id=cuid(),
            userId=user_id,
            volumeId=context.volume.id,
            readerType=reader_type,
            position="0",
            page=None,
            percent=percent,
            extra="{}",
            schemaVersion=3,
            locationType=reader_type,
            locationJson=location_json,
            contentFingerprint=content_fingerprint,
            mutationId=mutation_id,
            clientId=client_id,
            clientSequence=client_sequence,
            progressedAt=progressed_at,
            sourceProtocol=source_protocol,
            sourceDeviceName=source_device_name,
            createdAt=now,
            updatedAt=now,
        )
        progress = self._session.scalar(
            progress_insert.on_conflict_do_update(
                index_elements=[
                    LibraryReadingProgress.user_id,
                    LibraryReadingProgress.volume_id,
                ],
                set_={
                    "readerType": reader_type,
                    "percent": percent,
                    "schemaVersion": 3,
                    "locationType": reader_type,
                    "locationJson": location_json,
                    "contentFingerprint": content_fingerprint,
                    "mutationId": mutation_id,
                    "clientId": client_id,
                    "clientSequence": client_sequence,
                    "progressedAt": progressed_at,
                    "sourceProtocol": source_protocol,
                    "sourceDeviceName": source_device_name,
                    "updatedAt": now,
                },
            ).returning(LibraryReadingProgress)
        )
        if progress is None:
            raise RuntimeError("external progress upsert returned no row")
        history_insert = sqlite_insert(UserMediaHistory).values(
            id=cuid(),
            userId=user_id,
            mediaVersionId=context.media_version.id,
            lastVolumeId=context.volume.id,
            createdAt=now,
            updatedAt=now,
        )
        self._session.execute(
            history_insert.on_conflict_do_update(
                index_elements=[
                    UserMediaHistory.user_id,
                    UserMediaHistory.media_version_id,
                ],
                set_={
                    "lastVolumeId": context.volume.id,
                    "updatedAt": now,
                },
            )
        )
        return _progress_dto(progress)

    def list_bookmarks(
        self, user_id: str, volume_id: str, content_fingerprint: str
    ) -> list[ReaderBookmarkDto]:
        bookmarks = self._session.scalars(
            select(ReaderBookmark)
            .where(
                ReaderBookmark.user_id == user_id,
                ReaderBookmark.volume_id == volume_id,
                ReaderBookmark.content_fingerprint == content_fingerprint,
            )
            .order_by(ReaderBookmark.bookmark_created_at, ReaderBookmark.bookmark_id)
        ).all()
        return [_bookmark_dto(bookmark) for bookmark in bookmarks]

    def replace_bookmarks(
        self,
        *,
        user_id: str,
        volume_id: str,
        content_fingerprint: str,
        bookmarks: list[ReaderBookmarkDto],
        now: datetime,
    ) -> list[ReaderBookmarkDto]:
        rows = [
            {
                "id": cuid(),
                "userId": user_id,
                "volumeId": volume_id,
                "contentFingerprint": content_fingerprint,
                "bookmarkId": bookmark.bookmark_id,
                "locationJson": bookmark.location_json,
                "label": bookmark.label,
                "percent": bookmark.percent,
                "bookmarkCreatedAt": bookmark.bookmark_created_at.isoformat(),
                "createdAt": now,
                "updatedAt": now,
            }
            for bookmark in bookmarks
        ]
        self._session.execute(
            delete(ReaderBookmark).where(
                ReaderBookmark.user_id == user_id,
                ReaderBookmark.volume_id == volume_id,
                ReaderBookmark.content_fingerprint == content_fingerprint,
            )
        )
        for chunk in sqlite_parameter_chunks(rows, parameters_per_row=11):
            self._session.execute(sqlite_insert(ReaderBookmark).values(list(chunk)))
        return self.list_bookmarks(user_id, volume_id, content_fingerprint)
