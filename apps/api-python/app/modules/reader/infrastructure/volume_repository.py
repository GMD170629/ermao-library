"""SQLAlchemy ORM adapter for volume-scoped reader resources."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, delete, false, or_, select
from sqlalchemy.orm import Session

from app.models.auth import ReaderBookmark
from app.models.common import cuid
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryReadingProgress,
    LibraryReadingUnit,
    LibraryVolume,
    LibraryWork,
    UserMediaHistory,
)
from app.modules.reader.application.dto import (
    ReaderAccessScope,
    ReaderBookmarkDto,
    ReaderFileDto,
    ReaderMediaVersionDto,
    ReaderProgressDto,
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
        updated_at=progress.updated_at,
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
        visibility = LibraryVolume.id.is_not(None)
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
                sort_order=unit.sort_order,
                start_ms=unit.start_ms,
                end_ms=unit.end_ms,
                duration_ms=unit.duration_ms,
                metadata_json=unit.metadata_json,
            )
            for unit in units
        ]

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

    def save_progress(
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
        now: datetime,
    ) -> ReaderProgressDto:
        progress = self._session.scalar(
            select(LibraryReadingProgress).where(
                LibraryReadingProgress.user_id == user_id,
                LibraryReadingProgress.volume_id == context.volume.id,
            )
        )
        if progress is None:
            progress = LibraryReadingProgress(
                user_id=user_id,
                volume_id=context.volume.id,
                reader_type=reader_type,
                position="0",
                page=None,
                percent=percent,
                extra="{}",
                schema_version=3,
                location_type=reader_type,
                location_json=location_json,
                content_fingerprint=content_fingerprint,
                mutation_id=mutation_id,
                client_id=client_id,
                client_sequence=client_sequence,
                created_at=now,
                updated_at=now,
            )
            self._session.add(progress)
        else:
            progress.reader_type = reader_type
            progress.percent = percent
            progress.schema_version = 3
            progress.location_type = reader_type
            progress.location_json = location_json
            progress.content_fingerprint = content_fingerprint
            progress.mutation_id = mutation_id
            progress.client_id = client_id
            progress.client_sequence = client_sequence
            progress.updated_at = now

        history = self._session.scalar(
            select(UserMediaHistory).where(
                UserMediaHistory.user_id == user_id,
                UserMediaHistory.media_version_id == context.media_version.id,
            )
        )
        if history is None:
            self._session.add(
                UserMediaHistory(
                    user_id=user_id,
                    media_version_id=context.media_version.id,
                    last_volume_id=context.volume.id,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            history.last_volume_id = context.volume.id
            history.updated_at = now
        self._session.flush()
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
        self._session.execute(
            delete(ReaderBookmark).where(
                ReaderBookmark.user_id == user_id,
                ReaderBookmark.volume_id == volume_id,
                ReaderBookmark.content_fingerprint == content_fingerprint,
            )
        )
        for bookmark in bookmarks:
            self._session.add(
                ReaderBookmark(
                    id=cuid(),
                    user_id=user_id,
                    volume_id=volume_id,
                    content_fingerprint=content_fingerprint,
                    bookmark_id=bookmark.bookmark_id,
                    location_json=bookmark.location_json,
                    label=bookmark.label,
                    percent=bookmark.percent,
                    bookmark_created_at=bookmark.bookmark_created_at.isoformat(),
                    created_at=now,
                    updated_at=now,
                )
            )
        self._session.flush()
        return self.list_bookmarks(user_id, volume_id, content_fingerprint)
