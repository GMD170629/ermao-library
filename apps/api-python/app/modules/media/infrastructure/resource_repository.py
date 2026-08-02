"""SQLAlchemy ORM media resource query adapter."""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.media.application.resource_query import MediaFileResource


class SqlAlchemyMediaResourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_file(self, file_id: str) -> MediaFileResource | None:
        file = self._session.get(LibraryFile, file_id)
        return self._file_resource(file)

    def first_volume_file(self, volume_id: str) -> MediaFileResource | None:
        file = self._session.scalars(
            select(LibraryFile)
            .where(LibraryFile.volume_id == volume_id)
            .order_by(
                LibraryFile.sort_order,
                LibraryFile.created_at,
                LibraryFile.id,
            )
            .limit(1)
        ).first()
        return self._file_resource(file)

    def work_cover_path(self, work_id: str) -> str | None:
        explicit_cover = self._session.scalar(
            select(LibraryWork.cover_path).where(LibraryWork.id == work_id)
        )
        if explicit_cover:
            return str(explicit_cover)
        fallback = self._session.scalar(
            select(LibraryVolume.cover_path)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .where(
                LibraryMediaVersion.work_id == work_id,
                LibraryVolume.hidden.is_(False),
                LibraryVolume.cover_path.is_not(None),
                LibraryVolume.cover_path != "",
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
            .limit(1)
        )
        return str(fallback) if fallback else None

    def volume_cover_path(self, volume_id: str) -> str | None:
        cover_path = self._session.scalar(
            select(LibraryVolume.cover_path).where(LibraryVolume.id == volume_id)
        )
        return str(cover_path) if cover_path else None

    @staticmethod
    def _file_resource(file: LibraryFile | None) -> MediaFileResource | None:
        if file is None:
            return None
        return MediaFileResource(
            id=file.id,
            path=file.path,
            mime_type=file.mime_type,
        )
