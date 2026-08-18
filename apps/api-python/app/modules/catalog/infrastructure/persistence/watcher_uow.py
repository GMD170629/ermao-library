"""Transaction owner for watcher ingestion and targeted reconciliation."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Literal, Self, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.modules.catalog.domain.watcher import ReconcileConflict

from .models import LibraryRootRegistryLock
from .reconcile_diagnostic_repository import (
    SqlAlchemyReconcileDiagnosticRepository,
)
from .reconcile_source_repository import SqlAlchemyReconcileSourceRepository
from .repositories import SqlAlchemyOutboxPort
from .sqlite_errors import is_sqlite_busy_or_locked
from .topology_repository import SqlAlchemyTopologyRepository
from .watcher_repository import (
    SqlAlchemyReconcileLibraryRepository,
    SqlAlchemyWatcherJournalRepository,
)

logger = logging.getLogger(__name__)


class SqlAlchemyWatcherUnitOfWork:
    """Own one explicit SQLite writer transaction for watcher work."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._transaction: SessionTransaction | None = None
        self._committed = False

    def __enter__(self) -> Self:
        self._committed = False
        session = self._session_factory()
        self._session = session
        try:
            transaction = session.begin()
            self._transaction = transaction
            transaction.__enter__()
            self._acquire_writer_gate()
            self.libraries = SqlAlchemyReconcileLibraryRepository(session)
            self.watcher = SqlAlchemyWatcherJournalRepository(session)
            self.sources = SqlAlchemyReconcileSourceRepository(session)
            self.topology = SqlAlchemyTopologyRepository(session)
            self.diagnostics = SqlAlchemyReconcileDiagnosticRepository(session)
            self.outbox = SqlAlchemyOutboxPort(session)
            return self
        except BaseException:
            self._contain_failed_enter(session)
            raise

    def _acquire_writer_gate(self) -> None:
        if self._session is None:
            raise RuntimeError("Catalog watcher unit of work is not active")
        statement = (
            update(LibraryRootRegistryLock)
            .where(LibraryRootRegistryLock.id == 1)
            .values(fence=LibraryRootRegistryLock.fence)
        )
        try:
            result = self._session.execute(statement)
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise ReconcileConflict() from exc
            raise
        if cast(CursorResult[object], result).rowcount != 1:
            raise RuntimeError("current root registry lock is not initialized")
        self._session.flush()

    def _contain_failed_enter(self, session: Session) -> None:
        try:
            session.rollback()
        except Exception:
            logger.exception("catalog watcher unit of work enter rollback failed")
        try:
            session.close()
        except Exception:
            logger.exception("catalog watcher unit of work enter close failed")
        finally:
            self._session = None
            self._transaction = None

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        session = self._session
        transaction = self._transaction
        self._session = None
        self._transaction = None
        try:
            if session is not None and (
                exception_type is not None or not self._committed
            ):
                session.rollback()
            if transaction is not None and transaction.is_active:
                transaction.__exit__(exception_type, exception, traceback)
        finally:
            if session is not None:
                session.close()
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Catalog watcher unit of work is not active")
        try:
            self._session.commit()
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise ReconcileConflict() from exc
            raise
        self._committed = True

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()


class SqlAlchemyWatcherUowFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyWatcherUnitOfWork:
        return SqlAlchemyWatcherUnitOfWork(self._session_factory)


__all__ = ["SqlAlchemyWatcherUnitOfWork", "SqlAlchemyWatcherUowFactory"]
