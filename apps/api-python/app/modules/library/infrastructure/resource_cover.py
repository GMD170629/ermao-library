"""SQLAlchemy adapter for Resource cover regeneration."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LibraryReadableResource, LibraryReadableResourceMetadata
from app.modules.library.application.resource_cover import (
    MAX_RESOURCE_COVER_BYTES,
    PreparedResourceCover,
    PublishedResourceCover,
    ResourceCoverContext,
    ResourceCoverPublicationPort,
    ResourceCoverPort,
)

_IMAGE_SUFFIXES = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


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

    def current_cover_path(self, *, resource_id: str) -> str | None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        return metadata.cover_path if metadata is not None else None

    def mark_ready(
        self, *, resource_id: str, cover_path: str, now: datetime
    ) -> None:
        metadata = self._db.get(LibraryReadableResourceMetadata, resource_id)
        if metadata is None:
            raise LookupError(resource_id)
        metadata.cover_path = cover_path
        metadata.cover_status = "READY"
        metadata.updated_at = now


class FilesystemResourceCoverPublication(ResourceCoverPublicationPort):
    """Validated and recoverable publication under the Resource cover root."""

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root.resolve()
        self._cover_root = self._storage_root / "covers" / "resources"

    def prepare(
        self, *, resource_id: str, content: bytes
    ) -> PreparedResourceCover:
        if not resource_id or Path(resource_id).name != resource_id:
            raise ValueError("invalid resource identifier")
        if not content or len(content) > MAX_RESOURCE_COVER_BYTES:
            raise ValueError("resource cover exceeds the supported size")
        self._cover_root.mkdir(parents=True, exist_ok=True)
        temporary_path = self._cover_root / f".{resource_id}.{uuid4().hex}.part"
        try:
            temporary_path.write_bytes(content)
            with Image.open(temporary_path) as image:
                image_format = str(image.format or "").upper()
                image.verify()
            suffix = _IMAGE_SUFFIXES.get(image_format)
            if suffix is None:
                raise ValueError("resource cover is not a supported image")
        except (
            OSError,
            UnidentifiedImageError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            temporary_path.unlink(missing_ok=True)
            raise ValueError("resource cover could not be validated") from exc
        final_path = self._cover_root / f"{resource_id}{suffix}"
        return PreparedResourceCover(
            temporary_path=temporary_path,
            final_path=final_path,
            stored_path=str(final_path.relative_to(self._storage_root)),
        )

    def publish(
        self,
        prepared: PreparedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> PublishedResourceCover:
        del previous_stored_path
        backup_path = None
        if prepared.final_path.exists():
            backup_path = prepared.final_path.with_name(
                f".{prepared.final_path.name}.{uuid4().hex}.backup"
            )
            os.replace(prepared.final_path, backup_path)
        try:
            os.replace(prepared.temporary_path, prepared.final_path)
        except OSError:
            if backup_path is not None and backup_path.exists():
                os.replace(backup_path, prepared.final_path)
            prepared.temporary_path.unlink(missing_ok=True)
            raise
        return PublishedResourceCover(prepared=prepared, backup_path=backup_path)

    def revert(self, published: PublishedResourceCover) -> None:
        published.prepared.final_path.unlink(missing_ok=True)
        if published.backup_path is not None and published.backup_path.exists():
            os.replace(published.backup_path, published.prepared.final_path)

    def complete(
        self,
        published: PublishedResourceCover,
        *,
        previous_stored_path: str | None,
    ) -> None:
        if published.backup_path is not None:
            published.backup_path.unlink(missing_ok=True)
        if (
            previous_stored_path
            and previous_stored_path != published.prepared.stored_path
        ):
            self._remove(previous_stored_path)

    def _remove(self, stored_path: str) -> None:
        candidate = (self._storage_root / stored_path).resolve()
        try:
            candidate.relative_to(self._cover_root.resolve())
        except ValueError:
            return
        candidate.unlink(missing_ok=True)


__all__ = ["FilesystemResourceCoverPublication", "SqlAlchemyResourceCover"]
