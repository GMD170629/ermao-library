"""Named reader maintenance transaction boundary."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.modules.reader.infrastructure.navigation_maintenance import (
    SqlAlchemyEpubNavigationMaintenanceRepository,
)


class SqlAlchemyEpubNavigationMaintenanceUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self.navigation: SqlAlchemyEpubNavigationMaintenanceRepository

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        self.navigation = SqlAlchemyEpubNavigationMaintenanceRepository(self._session)
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
            raise RuntimeError("EPUB navigation unit of work is not active")
        self._session.commit()


__all__ = ["SqlAlchemyEpubNavigationMaintenanceUnitOfWork"]
