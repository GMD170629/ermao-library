"""SQLAlchemy transaction boundary for import application commands."""

from __future__ import annotations

from sqlalchemy.orm import Session


class SqlAlchemyImportUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
