"""Generate and publish a deterministic render artifact without changing its source."""

from __future__ import annotations

from pathlib import Path

from app.modules.publications.application.ports import (
    PublicationAccessScope,
    PublicationSource,
)
from app.modules.publications.application.render_ports import (
    PublicationRenderArtifactBuilder,
    PublicationRenderFileStore,
    PublicationRenderLookupUnitOfWorkFactory,
    PublicationRenderUnitOfWorkFactory,
)
from app.modules.publications.domain.model import PublicationNotFoundError
from app.modules.publications.domain.rendering import (
    RENDER_NORMALIZATION_IDENTIFIER,
    PublicationRenderArtifact,
)


class PublicationRenderSourceChangedError(Exception):
    """The source changed while its disposable render artifact was generated."""


class EnsurePublicationRenderArtifact:
    def __init__(
        self,
        *,
        lookup_unit_of_work_factory: PublicationRenderLookupUnitOfWorkFactory,
        unit_of_work_factory: PublicationRenderUnitOfWorkFactory,
        artifact_builder: PublicationRenderArtifactBuilder,
        file_store: PublicationRenderFileStore,
    ) -> None:
        self._lookup_unit_of_work_factory = lookup_unit_of_work_factory
        self._unit_of_work_factory = unit_of_work_factory
        self._artifact_builder = artifact_builder
        self._file_store = file_store

    def execute(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> tuple[PublicationRenderArtifact, Path]:
        source, cached = self._lookup(volume_id=volume_id, access_scope=access_scope)
        if cached is not None and self._cache_matches(source, cached):
            cached_path = self._file_store.resolve(cached.relative_path)
            if cached_path is not None:
                return cached, cached_path

        prepared = self._artifact_builder.build(source)
        if (
            source.size_bytes != prepared.source_size_bytes
            or source.mtime_ms != prepared.source_mtime_ms
        ):
            raise PublicationRenderSourceChangedError
        relative_path, published_path = self._file_store.publish(prepared)
        artifact = PublicationRenderArtifact(
            volume_id=source.volume_id,
            file_id=source.file_id,
            source_size_bytes=prepared.source_size_bytes,
            source_mtime_ms=prepared.source_mtime_ms,
            parser=prepared.source_parser,
            normalization=prepared.normalization,
            relative_path=relative_path,
            size_bytes=prepared.size_bytes,
            unreadable_resource_count=len(prepared.unreadable_hrefs),
        )
        with self._unit_of_work_factory() as unit_of_work:
            replaced = unit_of_work.render.replace_if_source_current(
                source=source,
                artifact=artifact,
            )
            if replaced:
                unit_of_work.commit()
        if not replaced:
            raise PublicationRenderSourceChangedError
        return artifact, published_path

    def _lookup(
        self,
        *,
        volume_id: str,
        access_scope: PublicationAccessScope,
    ) -> tuple[PublicationSource, PublicationRenderArtifact | None]:
        with self._lookup_unit_of_work_factory() as lookup:
            source = lookup.sources.find_source(
                volume_id=volume_id,
                access_scope=access_scope,
            )
            cached = lookup.cache.find(volume_id=volume_id)
        if source is None:
            raise PublicationNotFoundError
        return source, cached

    @staticmethod
    def _cache_matches(
        source: PublicationSource,
        cached: PublicationRenderArtifact,
    ) -> bool:
        return bool(
            cached.file_id == source.file_id
            and cached.source_size_bytes == source.size_bytes
            and cached.source_mtime_ms == source.mtime_ms
            and cached.normalization == RENDER_NORMALIZATION_IDENTIFIER
        )


__all__ = [
    "EnsurePublicationRenderArtifact",
    "PublicationRenderSourceChangedError",
]
