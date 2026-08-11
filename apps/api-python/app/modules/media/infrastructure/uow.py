"""Named transaction boundary for media data migrations."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.modules.media.infrastructure.comic_page_index_migration import (
    SqlAlchemyComicPageIndexMigrationRepository,
)


class SqlAlchemyComicPageIndexMigrationUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.page_indexes: SqlAlchemyComicPageIndexMigrationRepository

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.page_indexes = SqlAlchemyComicPageIndexMigrationRepository(self._session)
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
            raise RuntimeError("comic page-index migration unit of work is not active")
        self._session.commit()


__all__ = ["SqlAlchemyComicPageIndexMigrationUnitOfWork"]
