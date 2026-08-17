"""Crash-released cross-process root registry for Catalog create preflight."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import TracebackType
from typing import Self, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult, Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.engine import canonical_database_path
from app.db.current.sidecar_lock import (
    DatabaseSidecarLock,
    DatabaseSidecarLockTimeout,
)
from app.modules.catalog.application.ports import ReservedRoot
from app.modules.catalog.domain.errors import RootRegistryBusy
from app.modules.catalog.domain.root_paths import RootClaim

from .models import CatalogLibrary, LibraryRootRegistryLock
from .sqlite_errors import is_sqlite_busy_or_locked

logger = logging.getLogger(__name__)


class SqlAlchemyRootRegistryLease:
    def __init__(
        self,
        registry: SqlAlchemyRootRegistry,
        lock: DatabaseSidecarLock,
        owner_token: str,
        fence: int,
    ) -> None:
        self._registry = registry
        self._lock = lock
        self._owner_token = owner_token
        self.fence = fence
        self._released = False

    def __enter__(self) -> Self:
        return self

    def heartbeat(self) -> None:
        if self._released:
            raise RuntimeError("root registry lease is released")
        now = self._registry._clock()
        statement = (
            update(LibraryRootRegistryLock)
            .where(
                LibraryRootRegistryLock.id == 1,
                LibraryRootRegistryLock.owner_token == self._owner_token,
                LibraryRootRegistryLock.fence == self.fence,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + self._registry._lease_duration,
            )
        )
        try:
            with self._registry._session_factory() as session, session.begin():
                result = session.execute(statement)
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise RootRegistryBusy() from exc
            raise
        if cast(CursorResult[object], result).rowcount != 1:
            raise RootRegistryBusy("ROOT_REGISTRY_LEASE_LOST")

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        statement = (
            update(LibraryRootRegistryLock)
            .where(
                LibraryRootRegistryLock.id == 1,
                LibraryRootRegistryLock.owner_token == self._owner_token,
                LibraryRootRegistryLock.fence == self.fence,
            )
            .values(owner_token=None, lease_expires_at=None)
        )
        try:
            with self._registry._session_factory() as session, session.begin():
                session.execute(statement)
        except Exception:
            # The OS lock is authoritative for crash release. A stale owner
            # row must not turn a committed Create into a false failure.
            logger.exception("catalog root registry owner cleanup failed")
        finally:
            self._lock.release()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()


class SqlAlchemyRootRegistry:
    """Serialize Create's preflight, overlap check and independent UoW commit.

    The sidecar lock is process/crash released by the operating system.  The
    singleton row stores a short-lived fence for observability and stale-owner
    detection; it is never held as a SQLite transaction while the application
    UoW runs.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        database_path: str | Path | None = None,
        *,
        engine: Engine | None = None,
        timeout_seconds: float = 30.0,
        lease_seconds: float = 60.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if database_path is None:
            if engine is None or engine.url.database is None:
                raise ValueError("database_path or file-backed engine is required")
            database_path = engine.url.database
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._session_factory = session_factory
        self._database_path = canonical_database_path(database_path)
        self._timeout_seconds = timeout_seconds
        self._lease_duration = timedelta(seconds=lease_seconds)
        self._clock = clock

    def acquire(self, *, owner_token: str) -> SqlAlchemyRootRegistryLease:
        if not owner_token.strip():
            raise ValueError("owner_token must not be empty")
        lock = DatabaseSidecarLock(
            self._database_path,
            lock_suffix=".library-roots.lock",
            timeout_seconds=self._timeout_seconds,
            lock_label="library root registry",
        )
        try:
            lock.acquire()
        except DatabaseSidecarLockTimeout as exc:
            raise RootRegistryBusy() from exc
        try:
            now = self._clock()
            claim_statement = (
                update(LibraryRootRegistryLock)
                .where(LibraryRootRegistryLock.id == 1)
                .values(
                    fence=LibraryRootRegistryLock.fence + 1,
                    owner_token=owner_token,
                    heartbeat_at=now,
                    lease_expires_at=now + self._lease_duration,
                )
            )
            fence_statement = select(LibraryRootRegistryLock.fence).where(
                LibraryRootRegistryLock.id == 1
            )
            with self._session_factory() as session, session.begin():
                result = session.execute(claim_statement)
                fence_result = session.execute(fence_statement)
            fence = fence_result.scalar_one_or_none()
            if cast(CursorResult[object], result).rowcount != 1 or fence is None:
                raise RootRegistryBusy("ROOT_REGISTRY_ROW_MISSING")
            return SqlAlchemyRootRegistryLease(self, lock, owner_token, fence)
        except OperationalError as exc:
            lock.release()
            if is_sqlite_busy_or_locked(exc):
                raise RootRegistryBusy() from exc
            raise
        except BaseException:
            lock.release()
            raise

    def reserved_roots(self) -> tuple[ReservedRoot, ...]:
        statement = select(CatalogLibrary).order_by(CatalogLibrary.root_path_key)
        try:
            with self._session_factory() as session:
                rows = session.scalars(statement).all()
        except OperationalError as exc:
            if is_sqlite_busy_or_locked(exc):
                raise RootRegistryBusy() from exc
            raise
        return tuple(
            ReservedRoot(
                library_id=row.id,
                claim=RootClaim(
                    root_path_key=row.root_path_key,
                    components=_root_components(row.root_path_key),
                ),
            )
            for row in rows
        )


def _root_components(root_path_key: str) -> tuple[str, ...]:
    if "\\" in root_path_key or (len(root_path_key) >= 2 and root_path_key[1] == ":"):
        return tuple(PureWindowsPath(root_path_key).parts)
    return tuple(PurePosixPath(root_path_key).parts)


__all__ = [
    "RootRegistryBusy",
    "SqlAlchemyRootRegistry",
    "SqlAlchemyRootRegistryLease",
]
