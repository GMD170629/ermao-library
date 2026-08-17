"""Transaction owner for current Catalog commands and queries."""

from __future__ import annotations

import logging
from collections.abc import Callable
from types import TracebackType
from typing import Literal, Self, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

from app.modules.catalog.application.ports import UserAuthorizationPort
from app.modules.catalog.domain.errors import AclConflict

from .models import LibraryRootRegistryLock
from .repositories import (
    SqlAlchemyAuditPort,
    SqlAlchemyIgnoreRuleRepository,
    SqlAlchemyLibraryGrantRepository,
    SqlAlchemyLibraryQueryRepository,
    SqlAlchemyLibraryRepository,
    SqlAlchemyLibraryWritePolicy,
    SqlAlchemyOutboxPort,
)
from .sqlite_errors import is_sqlite_busy_or_locked

UserAuthorizationFactory = Callable[[Session], UserAuthorizationPort]
logger = logging.getLogger(__name__)


class SqlAlchemyLibraryUnitOfWork:
    """Own one explicit SQLite transaction; repositories never commit."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        user_authorization_factory: UserAuthorizationFactory,
    ) -> None:
        self._session_factory = session_factory
        self._user_authorization_factory = user_authorization_factory
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
            self.libraries = SqlAlchemyLibraryRepository(session)
            self.grants = SqlAlchemyLibraryGrantRepository(session)
            self.ignore_rules = SqlAlchemyIgnoreRuleRepository(session)
            self.users = self._user_authorization_factory(session)
            self.queries = SqlAlchemyLibraryQueryRepository(session)
            self.audit = SqlAlchemyAuditPort(session)
            self.outbox = SqlAlchemyOutboxPort(session)
            self.write_policy = SqlAlchemyLibraryWritePolicy(session)
            return self
        except BaseException:
            self._contain_failed_enter(session)
            raise

    def _contain_failed_enter(self, session: Session) -> None:
        """Best-effort cleanup without replacing the original enter failure."""

        try:
            session.rollback()
        except Exception:
            logger.exception("catalog unit of work enter rollback failed")
        try:
            session.close()
        except Exception:
            logger.exception("catalog unit of work enter close failed")
        finally:
            self._session = None
            self._transaction = None

    def _acquire_writer_gate(self) -> None:
        if self._session is None:
            raise RuntimeError("Catalog unit of work is not active")
        # SQLite has no row-level FOR UPDATE.  A typed no-op UPDATE obtains the
        # single writer reservation before ACL/count/state reads occur.
        statement = (
            update(LibraryRootRegistryLock)
            .where(LibraryRootRegistryLock.id == 1)
            .values(fence=LibraryRootRegistryLock.fence)
        )
        try:
            result = self._session.execute(statement)
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise AclConflict() from exc
            raise
        if cast(CursorResult[object], result).rowcount != 1:
            raise RuntimeError("current root registry lock is not initialized")
        self._session.flush()

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
            if session is not None and exception_type is not None:
                session.rollback()
            elif session is not None and not self._committed:
                # A command that forgets to call commit must not accidentally
                # publish its mutations when leaving the context.
                session.rollback()
            if transaction is not None and transaction.is_active:
                transaction.__exit__(exception_type, exception, traceback)
        finally:
            if session is not None:
                session.close()
        return False

    def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Catalog unit of work is not active")
        try:
            self._session.commit()
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise AclConflict() from exc
            raise
        self._committed = True

    def rollback(self) -> None:
        if self._session is not None:
            self._session.rollback()


__all__ = ["SqlAlchemyLibraryUnitOfWork"]
