from __future__ import annotations

from types import TracebackType
from typing import Literal, Self

from sqlalchemy.orm import Session, sessionmaker


class SqlAlchemyUnitOfWork:
    """Owns one transaction; repositories never commit independently."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self.session: Session | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self.session = self._session_factory()
        self._committed = False
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        del traceback
        if self.session is None:
            return False
        try:
            if exc_type is not None or not self._committed:
                self.session.rollback()
        finally:
            self.session.close()
            self.session = None
        return False

    def commit(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork must be entered before commit")
        self.session.commit()
        self._committed = True

    def rollback(self) -> None:
        if self.session is None:
            raise RuntimeError("UnitOfWork must be entered before rollback")
        self.session.rollback()
