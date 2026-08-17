from __future__ import annotations

from multiprocessing import Process, Queue
from pathlib import Path

import pytest

from app.db.current.lock import SchemaLock, SchemaLockTimeout


def _acquire_then_exit(database_path: str, ready: Queue[str]) -> None:
    lock = SchemaLock(database_path, timeout_seconds=1.0)
    lock.acquire()
    ready.put("acquired")


def test_lock_uses_canonical_database_path_and_sidecar(tmp_path: Path) -> None:
    database_path = tmp_path / "nested" / "library.sqlite3"
    alias = tmp_path / "alias"
    alias.symlink_to(database_path.parent, target_is_directory=True)

    lock = SchemaLock(alias / database_path.name, timeout_seconds=0.2)

    assert lock.database_path == database_path.resolve()
    assert lock.lock_path == database_path.with_name("library.sqlite3.schema.lock")
    with lock:
        assert lock.lock_path.exists()


def test_lock_times_out_while_another_handle_is_held(tmp_path: Path) -> None:
    database_path = tmp_path / "library.sqlite3"

    holder = SchemaLock(database_path, timeout_seconds=0.2)
    holder.acquire()
    try:
        with (
            pytest.raises(SchemaLockTimeout),
            SchemaLock(
                database_path,
                timeout_seconds=0.02,
                poll_interval_seconds=0.005,
            ),
        ):
            pass
    finally:
        holder.release()


def test_lock_releases_after_exception(tmp_path: Path) -> None:
    database_path = tmp_path / "library.sqlite3"
    lock = SchemaLock(database_path, timeout_seconds=0.2)

    with pytest.raises(RuntimeError):
        lock.acquire()
        try:
            raise RuntimeError("simulated initialization failure")
        finally:
            lock.release()

    with SchemaLock(database_path, timeout_seconds=0.2):
        pass


def test_lock_is_released_when_holding_process_exits(tmp_path: Path) -> None:
    database_path = tmp_path / "library.sqlite3"
    ready: Queue[str] = Queue()
    process = Process(target=_acquire_then_exit, args=(str(database_path), ready))
    process.start()
    process.join(timeout=2.0)

    assert process.exitcode == 0
    assert ready.get(timeout=1.0) == "acquired"
    with SchemaLock(database_path, timeout_seconds=0.2):
        pass
