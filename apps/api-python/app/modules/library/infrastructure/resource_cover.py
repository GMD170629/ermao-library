"""SQLAlchemy adapter for Resource cover regeneration."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LibraryReadableResource, LibraryReadableResourceMetadata
from app.modules.library.application.resource_cover import (
    ResourceCoverContext,
    ResourceCoverPort,
)


class SqlAlchemyResourceCover(ResourceCoverPort):
    """Persist Resource cover state without committing the caller transaction."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_context(
        self, *, book_id: str, resource_id: str
    ) -> ResourceCoverContext | None:
        row = self._db.execute(
            select(
                LibraryReadableResource.id,
                LibraryReadableResource.book_id,
                LibraryReadableResource.source_node_id,
            ).where(
                LibraryReadableResource.id == resource_id,
                LibraryReadableResource.book_id == book_id,
            )
        ).first()
        if row is None:
            return None
        return ResourceCoverContext(
            resource_id=str(row[0]),
            book_id=str(row[1]),
            source_node_id=str(row[2]),
        )

    def mark_pending(self, *, resource_id: str, now: datetime) -> None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            return
        metadata.cover_path = None
        metadata.cover_status = "PENDING"
        metadata.updated_at = now


__all__ = ["SqlAlchemyResourceCover"]
