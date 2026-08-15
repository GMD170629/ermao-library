"""ORM and filesystem adapters for disposable render artifacts."""

from __future__ import annotations

import os
import tempfile
import uuid
import zipfile
from pathlib import Path

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session

from app.models.library import LibraryFile, LibraryVolume
from app.modules.publications.application.ports import PublicationSource
from app.modules.publications.domain.rendering import (
    PreparedPublicationRenderArtifact,
    PublicationRenderArtifact,
)
from app.modules.publications.infrastructure.models import PublicationRenderCache


class SqlAlchemyPublicationRenderCacheReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, *, volume_id: str) -> PublicationRenderArtifact | None:
        cache = self._session.get(PublicationRenderCache, volume_id)
        if cache is None or cache.status != "READY":
            return None
        return PublicationRenderArtifact(
            volume_id=cache.volume_id,
            file_id=cache.file_id,
            source_size_bytes=cache.source_size_bytes,
            source_mtime_ms=cache.source_mtime_ms,
            parser=cache.parser,
            normalization=cache.normalization,
            relative_path=cache.relative_path,
            size_bytes=cache.size_bytes,
            unreadable_resource_count=cache.unreadable_resource_count,
        )


class SqlAlchemyPublicationRenderWriteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_if_source_current(
        self,
        *,
        source: PublicationSource,
        artifact: PublicationRenderArtifact,
    ) -> bool:
        first_file_id = (
            select(LibraryFile.id)
            .where(LibraryFile.volume_id == LibraryVolume.id)
            .order_by(
                LibraryFile.sort_order.asc(),
                LibraryFile.created_at.asc(),
                LibraryFile.id.asc(),
            )
            .limit(1)
            .correlate(LibraryVolume)
            .scalar_subquery()
        )
        source_is_current = exists(
            select(LibraryFile.id).where(
                LibraryFile.id == source.file_id,
                LibraryFile.volume_id == source.volume_id,
                LibraryFile.size_bytes == source.size_bytes,
                LibraryFile.mtime_ms == source.mtime_ms,
            )
        )
        current_volume_id = self._session.scalar(
            update(LibraryVolume)
            .where(
                LibraryVolume.id == source.volume_id,
                first_file_id == source.file_id,
                source_is_current,
            )
            .values(updated_at=LibraryVolume.updated_at)
            .returning(LibraryVolume.id)
        )
        if current_volume_id != source.volume_id:
            return False
        cache = self._session.get(PublicationRenderCache, source.volume_id)
        if cache is None:
            cache = PublicationRenderCache(volume_id=source.volume_id)
            self._session.add(cache)
        cache.file_id = artifact.file_id
        cache.source_size_bytes = artifact.source_size_bytes
        cache.source_mtime_ms = artifact.source_mtime_ms
        cache.parser = artifact.parser
        cache.normalization = artifact.normalization
        cache.relative_path = artifact.relative_path
        cache.size_bytes = artifact.size_bytes
        cache.status = "READY"
        cache.unreadable_resource_count = artifact.unreadable_resource_count
        return True


class LocalPublicationRenderFileStore:
    def __init__(self, cache_root: Path) -> None:
        self._cache_root = cache_root.resolve()

    def publish(self, prepared: PreparedPublicationRenderArtifact) -> tuple[str, Path]:
        artifact_id = uuid.uuid4().hex
        relative = Path(artifact_id[:2]) / f"{artifact_id}.epub"
        destination = (self._cache_root / relative).resolve()
        destination.relative_to(self._cache_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_value = tempfile.mkstemp(
            prefix=f".{artifact_id}.",
            suffix=".partial",
            dir=destination.parent,
        )
        temporary = Path(temporary_value)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(prepared.content)
                output.flush()
                os.fsync(output.fileno())
            if not self._matches(temporary, prepared):
                raise OSError("published render artifact failed verification")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return relative.as_posix(), destination

    def resolve(self, relative_path: str) -> Path | None:
        candidate = (self._cache_root / relative_path).resolve()
        try:
            candidate.relative_to(self._cache_root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    @staticmethod
    def _matches(path: Path, prepared: PreparedPublicationRenderArtifact) -> bool:
        if path.stat().st_size != prepared.size_bytes:
            return False
        try:
            with zipfile.ZipFile(path) as archive:
                return archive.testzip() is None
        except (OSError, zipfile.BadZipFile):
            return False


__all__ = [
    "LocalPublicationRenderFileStore",
    "SqlAlchemyPublicationRenderCacheReader",
    "SqlAlchemyPublicationRenderWriteRepository",
]
