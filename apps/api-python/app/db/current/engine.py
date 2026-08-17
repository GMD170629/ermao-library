"""SQLAlchemy engine construction for the current SQLite database."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine

from app.db.sqlite import register_sqlite_foreign_keys


def canonical_database_path(database_path: str | Path) -> Path:
    """Return the stable absolute path used for the database and its lock."""

    path = Path(database_path)
    if path == Path(":memory:"):
        raise ValueError("the current database requires a file-backed SQLite path")
    return path.expanduser().resolve(strict=False)


def sqlite_url(database_path: str | Path) -> URL:
    """Build a SQLAlchemy SQLite URL without assembling SQL or URL text."""

    return URL.create(
        "sqlite+pysqlite",
        database=str(canonical_database_path(database_path)),
    )


def create_current_engine(
    database_path: str | Path,
    *,
    timeout_seconds: float = 30.0,
) -> Engine:
    """Create a current-schema SQLite engine.

    SQLite connection behavior is expressed through SQLAlchemy's dialect
    arguments. No connection is opened until the returned engine is used.
    """

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    engine = create_engine(
        sqlite_url(database_path),
        connect_args={
            "check_same_thread": False,
            "timeout": timeout_seconds,
        },
        future=True,
    )
    register_sqlite_foreign_keys(engine)
    return engine
