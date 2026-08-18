"""SQLAlchemy ORM media resource query adapter."""

from __future__ import annotations

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.core.authorization import AuthorizationContext, volume_visibility_predicate
from app.models.library import (
    LibraryFile,
    LibraryVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.media.application.resource_query import MediaFileResource
from app.modules.media.application.volume_archive import (
    VolumeArchiveSelection,
    VolumeArchiveSource,
)


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

    def get_volume_archive_selection(
        self,
        *,
        actor: AuthorizationContext,
        work_id: str,
        volume_ids: tuple[str, ...],
    ) -> VolumeArchiveSelection | None:
        rows = self._session.execute(
            select(LibraryWork.title, LibraryVolume, LibraryFile)
            .join(
                LibraryVersion,
                LibraryVersion.work_id == LibraryWork.id,
            )
            .join(
                LibraryVolume,
                LibraryVolume.version_id == LibraryVersion.id,
            )
            .outerjoin(LibraryFile, LibraryFile.volume_id == LibraryVolume.id)
            .where(
                LibraryWork.id == work_id,
                LibraryVolume.id.in_(volume_ids),
                LibraryVolume.hidden.is_(False),
                volume_visibility_predicate(actor),
            )
            .order_by(
                LibraryVersion.source_key,
                LibraryVolume.sort_order,
                LibraryVolume.created_at,
                LibraryVolume.id,
                LibraryFile.sort_order,
                LibraryFile.created_at,
                LibraryFile.id,
            )
        ).all()
        if not rows:
            return None
        sources_by_volume: dict[str, VolumeArchiveSource] = {}
        for work_title, volume, file in rows:
            existing = sources_by_volume.get(volume.id)
            if existing is not None and (existing.source_path or file is None):
                continue
            sources_by_volume[volume.id] = VolumeArchiveSource(
                volume_id=volume.id,
                volume_title=volume.title,
                source_path=file.path if file is not None else "",
            )
        return VolumeArchiveSelection(
            work_title=str(rows[0][0]),
            sources=tuple(sources_by_volume.values()),
        )

    def work_cover_path(self, work_id: str) -> str | None:
        explicit_cover = self._session.scalar(
            select(LibraryWork.cover_path).where(LibraryWork.id == work_id)
        )
        if explicit_cover:
            return str(explicit_cover)
        fallback = self._session.scalar(
            select(LibraryVolume.cover_path)
            .join(
                LibraryVersion,
                LibraryVersion.id == LibraryVolume.version_id,
            )
            .where(
                LibraryVersion.work_id == work_id,
                LibraryVolume.hidden.is_(False),
                LibraryVolume.cover_path.is_not(None),
                LibraryVolume.cover_path != "",
            )
            .order_by(
                case(
                    (LibraryVersion.source_key == "EBOOK", 0),
                    (LibraryVersion.source_key == "COMIC", 1),
                    (LibraryVersion.source_key == "AUDIOBOOK", 2),
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
