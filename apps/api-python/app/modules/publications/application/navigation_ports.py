"""Ports for the Publication-owned lazy navigation projection."""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self

from app.modules.publications.application.ports import (
    PublicationSource,
    PublicationSourceRepository,
)
from app.modules.publications.domain.navigation import (
    PublicationNavigationCacheIdentity,
    PublicationNavigationCacheState,
    PublicationNavigationEntry,
    PublicationParserProfile,
)


class PublicationNavigationCacheReader(Protocol):
    def find(self, *, resource_id: str) -> PublicationNavigationCacheState | None: ...

    def has_materialized_projection(self, *, resource_id: str) -> bool: ...


class PublicationParserProfileResolver(Protocol):
    def resolve(self, *, source_format: str) -> PublicationParserProfile | None: ...


class PublicationNavigationWriteRepository(Protocol):
    def invalidate(self, *, resource_id: str) -> None: ...

    def replace(
        self,
        *,
        source: PublicationSource,
        identity: PublicationNavigationCacheIdentity,
        entries: tuple[PublicationNavigationEntry, ...],
    ) -> None: ...


class PublicationNavigationUnitOfWork(Protocol):
    navigation: PublicationNavigationWriteRepository

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class PublicationNavigationUnitOfWorkFactory(Protocol):
    def __call__(self) -> PublicationNavigationUnitOfWork: ...


class PublicationNavigationLookupUnitOfWork(Protocol):
    sources: PublicationSourceRepository
    cache: PublicationNavigationCacheReader

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class PublicationNavigationLookupUnitOfWorkFactory(Protocol):
    def __call__(self) -> PublicationNavigationLookupUnitOfWork: ...


__all__ = [
    "PublicationNavigationCacheReader",
    "PublicationNavigationLookupUnitOfWork",
    "PublicationNavigationLookupUnitOfWorkFactory",
    "PublicationNavigationUnitOfWork",
    "PublicationNavigationUnitOfWorkFactory",
    "PublicationNavigationWriteRepository",
    "PublicationParserProfileResolver",
]
