"""Short-timeout metadata write sessions derived from a caller database."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.db.sqlite import SHORT_WRITE_OPERATION_LIMIT_SECONDS, create_sqlite_engine


@contextmanager
def metadata_short_write_session(source: Session) -> Iterator[Session]:
    """End the source read scope and yield a 500ms SQLite writer."""

    bind = source.get_bind()
    source_engine = bind.engine if isinstance(bind, Connection) else bind
    source.close()
    writer_engine, owns_engine = _short_writer_engine(source_engine)
    try:
        with Session(
            bind=writer_engine,
            autoflush=False,
            expire_on_commit=False,
        ) as writer:
            yield writer
    finally:
        if owns_engine:
            writer_engine.dispose()


def _short_writer_engine(source_engine: Engine) -> tuple[Engine, bool]:
    database = source_engine.url.database
    if (
        source_engine.url.get_backend_name() != "sqlite"
        or not database
        or database == ":memory:"
    ):
        return source_engine, False
    return (
        create_sqlite_engine(
            Path(database),
            timeout_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
            transaction_time_budget_seconds=SHORT_WRITE_OPERATION_LIMIT_SECONDS,
        ),
        True,
    )
