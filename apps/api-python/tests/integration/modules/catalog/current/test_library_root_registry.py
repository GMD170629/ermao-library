from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.lock import SchemaLock
from app.db.current.runner import upgrade_current_schema
from app.db.current.sidecar_lock import DatabaseSidecarLockTimeout
from app.modules.catalog.domain.errors import RootRegistryBusy
from app.modules.catalog.domain.library import (
    Library,
    LibraryControlState,
    WritePolicy,
)
from app.modules.catalog.domain.model import OrganizationMode, PathComparison
from app.modules.catalog.domain.root_paths import RegisteredRoot
from app.modules.catalog.infrastructure.persistence import (
    LibraryRootRegistryLock,
    SqlAlchemyLibraryRepository,
    SqlAlchemyRootRegistry,
)


class _SqliteBusyError(Exception):
    sqlite_errorcode = 5


def _busy_operational_error() -> OperationalError:
    return OperationalError(None, None, _SqliteBusyError("database is locked"))


def _raise_busy_on_commit(_connection: object) -> None:
    raise _busy_operational_error()


def _raise_busy_before_execute(
    _connection: object,
    _cursor: object,
    _statement: object,
    _parameters: object,
    _context: object,
    _executemany: object,
) -> None:
    raise _busy_operational_error()


@pytest.fixture
def root_database(
    tmp_path: Path,
) -> Iterator[tuple[Path, sessionmaker[Session], Engine]]:
    database_path = tmp_path / "catalog-root-registry.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    bootstrap_system(engine)
    yield database_path, sessionmaker(engine), engine
    engine.dispose()


def _removing_library() -> Library:
    now = datetime.now(UTC)
    library = Library.create(
        library_id="library-removing",
        name="Removing",
        root=RegisteredRoot(
            "/srv/removing",
            "/srv/removing",
            ("/", "srv", "removing"),
        ),
        organization_mode=OrganizationMode.FLAT,
        path_comparison=PathComparison.SENSITIVE,
        write_policy=WritePolicy.READ_ONLY,
        now=now,
    )
    return replace(library, control_state=LibraryControlState.REMOVING)


def test_registry_returns_removing_claims_and_monotonic_fence(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, _engine = root_database
    with session_factory.begin() as session:
        SqlAlchemyLibraryRepository(session).insert(_removing_library())
    registry = SqlAlchemyRootRegistry(session_factory, database_path)

    with registry.acquire(owner_token="owner-1") as first:
        first_fence = first.fence
        claims = registry.reserved_roots()
        assert claims[0].library_id == "library-removing"
        assert claims[0].claim.root_path_key == "/srv/removing"
    with registry.acquire(owner_token="owner-2") as second:
        assert second.fence > first_fence


def test_schema_and_library_root_sidecar_locks_are_independent(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, _engine = root_database
    schema_lock = SchemaLock(database_path, timeout_seconds=0.05)
    registry = SqlAlchemyRootRegistry(
        session_factory,
        database_path,
        timeout_seconds=0.05,
    )

    with schema_lock, registry.acquire(owner_token="owner-1"):
        root_lock_path = database_path.with_name(
            f"{database_path.name}.library-roots.lock"
        )
        assert root_lock_path.exists()
        assert root_lock_path != schema_lock.lock_path


def test_two_root_registries_are_mutually_exclusive_with_stable_timeout(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, _engine = root_database
    holder = SqlAlchemyRootRegistry(session_factory, database_path)
    contender = SqlAlchemyRootRegistry(
        session_factory,
        database_path,
        timeout_seconds=0.01,
    )

    with (
        holder.acquire(owner_token="owner-1"),
        pytest.raises(RootRegistryBusy) as raised,
    ):
        contender.acquire(owner_token="owner-2")

    assert raised.value.code == "ROOT_REGISTRY_BUSY"
    assert isinstance(raised.value.__cause__, DatabaseSidecarLockTimeout)


def test_registry_acquire_database_busy_preserves_cause_and_releases_os_lock(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, _engine = root_database
    fast_engine = create_current_engine(database_path, timeout_seconds=0.01)
    fast_factory = sessionmaker(fast_engine)
    registry = SqlAlchemyRootRegistry(fast_factory, database_path)
    blocker = session_factory()
    blocker.execute(
        update(LibraryRootRegistryLock)
        .where(LibraryRootRegistryLock.id == 1)
        .values(fence=LibraryRootRegistryLock.fence + 1)
    )
    try:
        with pytest.raises(RootRegistryBusy) as raised:
            registry.acquire(owner_token="busy-owner")
        assert isinstance(raised.value.__cause__, OperationalError)
    finally:
        blocker.rollback()
        blocker.close()

    try:
        with registry.acquire(owner_token="retry-owner"):
            pass
    finally:
        fast_engine.dispose()


def test_registry_acquire_commit_busy_preserves_cause_and_releases_os_lock(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, engine = root_database
    registry = SqlAlchemyRootRegistry(session_factory, database_path)
    event.listen(engine, "commit", _raise_busy_on_commit)
    try:
        with pytest.raises(RootRegistryBusy) as raised:
            registry.acquire(owner_token="commit-busy")
    finally:
        event.remove(engine, "commit", _raise_busy_on_commit)

    assert isinstance(raised.value.__cause__, OperationalError)
    with registry.acquire(owner_token="retry-owner"):
        pass


def test_registry_heartbeat_maps_execute_and_commit_busy(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, _engine = root_database
    fast_engine = create_current_engine(database_path, timeout_seconds=0.01)
    registry = SqlAlchemyRootRegistry(sessionmaker(fast_engine), database_path)
    lease = registry.acquire(owner_token="heartbeat-owner")
    blocker = session_factory()
    blocker.execute(
        update(LibraryRootRegistryLock)
        .where(LibraryRootRegistryLock.id == 1)
        .values(fence=LibraryRootRegistryLock.fence + 1)
    )
    try:
        with pytest.raises(RootRegistryBusy) as execute_busy:
            lease.heartbeat()
        assert isinstance(execute_busy.value.__cause__, OperationalError)
    finally:
        blocker.rollback()
        blocker.close()

    event.listen(fast_engine, "commit", _raise_busy_on_commit)
    try:
        with pytest.raises(RootRegistryBusy) as commit_busy:
            lease.heartbeat()
    finally:
        event.remove(fast_engine, "commit", _raise_busy_on_commit)
        lease.release()
        fast_engine.dispose()
    assert isinstance(commit_busy.value.__cause__, OperationalError)


def test_reserved_root_busy_is_stable_and_preserves_cause(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, engine = root_database
    registry = SqlAlchemyRootRegistry(session_factory, database_path)
    event.listen(engine, "before_cursor_execute", _raise_busy_before_execute)
    try:
        with pytest.raises(RootRegistryBusy) as raised:
            registry.reserved_roots()
    finally:
        event.remove(engine, "before_cursor_execute", _raise_busy_before_execute)

    assert isinstance(raised.value.__cause__, OperationalError)


def test_release_cleanup_failure_does_not_reverse_committed_result(
    root_database: tuple[Path, sessionmaker[Session], Engine],
) -> None:
    database_path, session_factory, engine = root_database
    registry = SqlAlchemyRootRegistry(session_factory, database_path)
    lease = registry.acquire(owner_token="committed-owner")
    event.listen(engine, "before_cursor_execute", _raise_busy_before_execute)
    try:
        lease.release()
    finally:
        event.remove(engine, "before_cursor_execute", _raise_busy_before_execute)

    with session_factory() as session:
        stale_row = session.get(LibraryRootRegistryLock, 1)
        assert stale_row is not None
        assert stale_row.owner_token == "committed-owner"
    with registry.acquire(owner_token="next-owner"):
        pass
