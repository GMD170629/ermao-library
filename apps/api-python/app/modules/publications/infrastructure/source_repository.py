"""SQLAlchemy source lookup scoped to the authenticated actor."""

from __future__ import annotations

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)


class SqlAlchemyPublicationSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_source(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> PublicationSource | None:
        visibility: ColumnElement[bool] = false()
        if access_scope.is_admin:
            visibility = LibraryVolume.id.is_not(None)
        else:
            clauses: list[ColumnElement[bool]] = []
            if access_scope.monitor_folder_ids:
                clauses.append(
                    LibraryVolume.monitor_folder_id.in_(access_scope.monitor_folder_ids)
                )
            if access_scope.can_view_manual_imports:
                clauses.append(LibraryVolume.monitor_folder_id.is_(None))
            if clauses:
                visibility = or_(*clauses)
        row = self._session.execute(
            select(LibraryWork, LibraryVolume, LibraryFile)
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.work_id == LibraryWork.id,
            )
            .join(
                LibraryVolume,
                LibraryVolume.media_version_id == LibraryMediaVersion.id,
            )
            .join(LibraryFile, LibraryFile.volume_id == LibraryVolume.id)
            .where(
                LibraryVolume.id == volume_id,
                LibraryVolume.hidden.is_(False),
                visibility,
            )
            .order_by(LibraryFile.sort_order, LibraryFile.created_at, LibraryFile.id)
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        work, volume, source = row
        return PublicationSource(
            volume_id=volume.id,
            file_id=source.id,
            source_format=volume.format.lower(),
            path=source.path,
            full_hash=source.full_hash,
            title=volume.title or work.title,
            author=work.author,
        )
