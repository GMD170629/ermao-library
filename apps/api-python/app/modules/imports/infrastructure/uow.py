"""SQLAlchemy transaction boundary for import application commands."""

from __future__ import annotations

from sqlalchemy.orm import Session


class SqlAlchemyImportUnitOfWork:
    def __init__(self, session: Session, *, close_on_release: bool = False) -> None:
        self._session = session
        self._close_on_release = close_on_release

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def release(self) -> None:
        self._session.commit()
        if self._close_on_release:
            self._session.close()
