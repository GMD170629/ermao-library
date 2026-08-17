"""Transaction owner for generation-scoped catalog scans."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Literal, Self, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.modules.catalog.domain.scan import ScanConflict

from .models import LibraryRootRegistryLock
from .repositories import (
    SqlAlchemyAuditPort,
    SqlAlchemyLibraryGrantRepository,
    SqlAlchemyOutboxPort,
)
from .scan_run_repositories import (
    SqlAlchemyFullScanRepository,
    SqlAlchemyRootScanWorkRepository,
    SqlAlchemyScanLibraryRepository,
)
from .source_observation_repositories import (
    SqlAlchemyPathCollisionRepository,
    SqlAlchemyScanDiagnosticRepository,
    SqlAlchemySourceObservationRepository,
)
from .sqlite_errors import is_sqlite_busy_or_locked
from .topology_repository import SqlAlchemyTopologyRepository

logger = logging.getLogger(__name__)


class SqlAlchemyScanUnitOfWork:
    """Own one explicit writer transaction for a bounded scan mutation."""

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
            self.libraries = SqlAlchemyScanLibraryRepository(session)
            self.scans = SqlAlchemyFullScanRepository(session)
            self.work_items = SqlAlchemyRootScanWorkRepository(session)
            self.sources = SqlAlchemySourceObservationRepository(session)
            self.topology = SqlAlchemyTopologyRepository(session)
            self.diagnostics = SqlAlchemyScanDiagnosticRepository(session)
            self.collisions = SqlAlchemyPathCollisionRepository(session)
            self.grants = SqlAlchemyLibraryGrantRepository(session)
            self.audit = SqlAlchemyAuditPort(session)
            self.outbox = SqlAlchemyOutboxPort(session)
            return self
        except BaseException:
            self._contain_failed_enter(session)
            raise

    def _acquire_writer_gate(self) -> None:
        if self._session is None:
            raise RuntimeError("Catalog scan unit of work is not active")
        statement = (
            update(LibraryRootRegistryLock)
            .where(LibraryRootRegistryLock.id == 1)
            .values(fence=LibraryRootRegistryLock.fence)
        )
        try:
            result = self._session.execute(statement)
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise ScanConflict() from exc
            raise
        if cast(CursorResult[object], result).rowcount != 1:
            raise RuntimeError("current root registry lock is not initialized")
        self._session.flush()

    def _contain_failed_enter(self, session: Session) -> None:
        try:
            session.rollback()
        except Exception:
            logger.exception("catalog scan unit of work enter rollback failed")
        try:
            session.close()
        except Exception:
            logger.exception("catalog scan unit of work enter close failed")
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
            raise RuntimeError("Catalog scan unit of work is not active")
        try:
            self._session.commit()
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise ScanConflict() from exc
            raise
        self._committed = True

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()


class SqlAlchemyScanUowFactory:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def __call__(self) -> SqlAlchemyScanUnitOfWork:
        return SqlAlchemyScanUnitOfWork(self._session_factory)


__all__ = ["SqlAlchemyScanUnitOfWork", "SqlAlchemyScanUowFactory"]
