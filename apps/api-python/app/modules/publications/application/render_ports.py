"""Application ports for disposable publication render artifacts."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from app.modules.publications.application.ports import (
    PublicationSource,
    PublicationSourceRepository,
)
from app.modules.publications.domain.rendering import (
    PreparedPublicationRenderArtifact,
    PublicationRenderArtifact,
)


class PublicationRenderArtifactBuilder(Protocol):
    def build(self, source: PublicationSource) -> PreparedPublicationRenderArtifact: ...


class PublicationRenderCacheReader(Protocol):
    def find(self, *, volume_id: str) -> PublicationRenderArtifact | None: ...


class PublicationRenderWriteRepository(Protocol):
    def replace_if_source_current(
        self,
        *,
        source: PublicationSource,
        artifact: PublicationRenderArtifact,
    ) -> bool: ...


class PublicationRenderFileStore(Protocol):
    def publish(
        self, prepared: PreparedPublicationRenderArtifact
    ) -> tuple[str, Path]: ...

    def resolve(self, relative_path: str) -> Path | None: ...


class PublicationRenderLookupUnitOfWork(Protocol):
    sources: PublicationSourceRepository
    cache: PublicationRenderCacheReader

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class PublicationRenderUnitOfWork(Protocol):
    render: PublicationRenderWriteRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class PublicationRenderLookupUnitOfWorkFactory(Protocol):
    def __call__(self) -> PublicationRenderLookupUnitOfWork: ...


class PublicationRenderUnitOfWorkFactory(Protocol):
    def __call__(self) -> PublicationRenderUnitOfWork: ...


__all__ = [
    "PublicationRenderArtifactBuilder",
    "PublicationRenderCacheReader",
    "PublicationRenderFileStore",
    "PublicationRenderLookupUnitOfWork",
    "PublicationRenderLookupUnitOfWorkFactory",
    "PublicationRenderUnitOfWork",
    "PublicationRenderUnitOfWorkFactory",
    "PublicationRenderWriteRepository",
]
