"""Typed bootstrap transaction for a fresh current database."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.current.engine import create_current_engine
from app.db.current.lock import schema_lock
from app.db.current.runner import upgrade_current_schema_unlocked
from app.modules.catalog.infrastructure.persistence.models import (
    LibraryRootRegistryLock,
)
from app.modules.system.infrastructure.persistence.models import SystemInstance

SYSTEM_INSTANCE_ID = 1
Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return an aware UTC timestamp for bootstrap-created rows."""

    return datetime.now(UTC)


def bootstrap_system(engine: Engine, *, clock: Clock = utc_now) -> None:
    """Insert the singleton system and root-registry rows in one transaction.

    The function intentionally assumes migrations already created the table;
    schema creation and row creation remain separate responsibilities.
    """

    with Session(engine) as session, session.begin():
        system = session.get(SystemInstance, SYSTEM_INSTANCE_ID)
        if system is None:
            session.add(
                SystemInstance(
                    id=SYSTEM_INSTANCE_ID,
                    created_at=clock(),
                    identity_bootstrap_completed_at=None,
                )
            )
        root_registry_lock = session.get(LibraryRootRegistryLock, 1)
        if root_registry_lock is None:
            session.add(LibraryRootRegistryLock(id=1))


def initialize_current_database(
    database_path: str | Path,
    *,
    lock_timeout_seconds: float = 30.0,
    engine_timeout_seconds: float = 30.0,
    clock: Clock = utc_now,
) -> None:
    """Run current migrations and typed bootstrap under one process lock."""

    engine = create_current_engine(
        database_path,
        timeout_seconds=engine_timeout_seconds,
    )
    try:
        with schema_lock(database_path, timeout_seconds=lock_timeout_seconds):
            upgrade_current_schema_unlocked(engine)
            bootstrap_system(engine, clock=clock)
    finally:
        engine.dispose()
