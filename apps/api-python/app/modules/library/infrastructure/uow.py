"""SQLAlchemy unit of work for bounded facet index repair batches."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from app.modules.library.infrastructure.facet_index import (
    SqlAlchemyFacetIndexRepository,
)


class SqlAlchemyFacetIndexUnitOfWork:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._db: Session | None = None
        self.facets: SqlAlchemyFacetIndexRepository

    def __enter__(self) -> Self:
        self._db = self._session_factory()
        self.facets = SqlAlchemyFacetIndexRepository(self._db)
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._db is None:
            return
        if exception is not None:
            self._db.rollback()
        self._db.close()
        self._db = None

    def commit(self) -> None:
        if self._db is None:
            raise RuntimeError("facet index unit of work is not active")
        self._db.commit()
