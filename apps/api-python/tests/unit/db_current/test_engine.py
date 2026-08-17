from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.db.current.engine import create_current_engine
from app.db.sqlite import create_sqlite_engine


def _assert_foreign_keys_enabled(engine) -> None:
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    engine.dispose()


def test_legacy_sqlite_engine_enables_foreign_keys_on_new_connections(
    tmp_path: Path,
) -> None:
    _assert_foreign_keys_enabled(create_sqlite_engine(tmp_path / "legacy.sqlite3"))


def test_current_sqlite_engine_enables_foreign_keys_on_new_connections(
    tmp_path: Path,
) -> None:
    _assert_foreign_keys_enabled(create_current_engine(tmp_path / "current.sqlite3"))


def test_foreign_key_registration_is_not_tied_to_legacy_maintenance_engine(
    tmp_path: Path,
) -> None:
    engine = create_current_engine(tmp_path / "current.sqlite3")
    try:
        assert engine.url.get_backend_name() == "sqlite"
        with engine.connect() as connection:
            assert connection.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()
