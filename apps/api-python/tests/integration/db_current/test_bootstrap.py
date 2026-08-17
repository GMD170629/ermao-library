from __future__ import annotations

from datetime import UTC, datetime
from multiprocessing import Process, Queue
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.current.bootstrap import bootstrap_system
from app.db.current.engine import create_current_engine
from app.db.current.lock import schema_lock
from app.db.current.runner import (
    upgrade_current_schema,
    upgrade_current_schema_unlocked,
)
from app.modules.catalog.infrastructure.persistence.models import (
    LibraryRootRegistryLock,
)
from app.modules.system.infrastructure.persistence.models import SystemInstance


def _initialize_in_process(database_path: str, completed: Queue[str]) -> None:
    engine = create_current_engine(database_path)
    try:
        with schema_lock(database_path, timeout_seconds=5.0):
            upgrade_current_schema_unlocked(engine)
            bootstrap_system(engine)
        completed.put("ok")
    finally:
        engine.dispose()


def _system_rows(engine: Engine) -> list[SystemInstance]:
    with Session(engine) as session:
        return list(session.scalars(select(SystemInstance)))


def _root_lock_rows(engine: Engine) -> list[LibraryRootRegistryLock]:
    with Session(engine) as session:
        return list(session.scalars(select(LibraryRootRegistryLock)))


def test_system_bootstrap_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    try:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)

        bootstrap_system(engine, clock=lambda: created_at)
        bootstrap_system(engine, clock=lambda: datetime(2027, 1, 1, tzinfo=UTC))

        rows = _system_rows(engine)
        assert len(rows) == 1
        assert rows[0].id == 1
        assert rows[0].created_at == created_at
        assert rows[0].identity_bootstrap_completed_at is None
        assert [row.id for row in _root_lock_rows(engine)] == [1]
    finally:
        engine.dispose()


def test_system_bootstrap_rolls_back_on_insert_failure(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    upgrade_current_schema(database_path)
    engine = create_current_engine(database_path)
    try:

        def fail_before_insert(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("simulated bootstrap failure")

        event.listen(SystemInstance, "before_insert", fail_before_insert)
        try:
            with pytest.raises(RuntimeError, match="simulated bootstrap failure"):
                bootstrap_system(engine)
        finally:
            event.remove(SystemInstance, "before_insert", fail_before_insert)

        assert _system_rows(engine) == []
        assert _root_lock_rows(engine) == []
    finally:
        engine.dispose()


def test_two_processes_initialize_one_current_system(tmp_path: Path) -> None:
    database_path = tmp_path / "current.sqlite3"
    completed: Queue[str] = Queue()
    processes = [
        Process(target=_initialize_in_process, args=(str(database_path), completed))
        for _ in range(2)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10.0)

    assert [process.exitcode for process in processes] == [0, 0]
    assert [completed.get(timeout=1.0) for _ in processes] == ["ok", "ok"]

    engine = create_current_engine(database_path)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "alembic_version_v2" in tables
        assert "alembic_version" not in tables
        assert len(_system_rows(engine)) == 1
    finally:
        engine.dispose()
