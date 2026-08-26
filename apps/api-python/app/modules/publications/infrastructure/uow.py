"""Transaction boundary for publishing a generated navigation projection."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.contracts.library_navigation import LibraryNavigationProjection
from app.modules.publications.application.navigation_ports import (
    PublicationNavigationCacheReader,
    PublicationNavigationWriteRepository,
)
from app.modules.publications.application.ports import PublicationSourceRepository
from app.modules.publications.infrastructure.navigation_cache import (
    SqlAlchemyPublicationNavigationCacheReader,
    SqlAlchemyPublicationNavigationWriteRepository,
)

PublicationSourceFactory = Callable[[Session], PublicationSourceRepository]
LibraryNavigationFactory = Callable[[Session], LibraryNavigationProjection]


class SqlAlchemyPublicationNavigationLookupUnitOfWork:
    """Short read transaction closed before Publication filesystem parsing."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        source_factory: PublicationSourceFactory,
        library_navigation_factory: LibraryNavigationFactory,
    ) -> None:
        self._session_factory = session_factory
        self._source_factory = source_factory
        self._library_navigation_factory = library_navigation_factory
        self._session: Session | None = None
        self.sources: PublicationSourceRepository
        self.cache: PublicationNavigationCacheReader

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.sources = self._source_factory(self._session)
        self.cache = SqlAlchemyPublicationNavigationCacheReader(
            self._session,
            self._library_navigation_factory(self._session),
        )
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        self._session.rollback()
        self._session.close()
        self._session = None


class SqlAlchemyPublicationNavigationUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        library_navigation_factory: LibraryNavigationFactory,
    ) -> None:
        self._session_factory = session_factory
        self._library_navigation_factory = library_navigation_factory
        self._session: Session | None = None
        self.navigation: PublicationNavigationWriteRepository

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.navigation = SqlAlchemyPublicationNavigationWriteRepository(
            self._session,
            self._library_navigation_factory(self._session),
        )
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._session is None:
            return
        if exception_type is not None:
            self._session.rollback()
        self._session.close()
        self._session = None

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Publication navigation unit of work is not active")
        self._session.commit()


__all__ = [
    "SqlAlchemyPublicationNavigationLookupUnitOfWork",
    "SqlAlchemyPublicationNavigationUnitOfWork",
]
