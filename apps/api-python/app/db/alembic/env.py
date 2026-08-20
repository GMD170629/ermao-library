"""Alembic migration environment for the Shuku Starship SQLite database."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

import app.models  # noqa: F401 — register all mapped tables
from app.core.config import get_settings
from app.db.base import Base
from app.db.sqlite import create_sqlite_engine

config = context.config

# Do not call logging.config.fileConfig here: Alembic CLI can configure logging
# separately. Loading alembic.ini logging from app startup/tests resets the
# process logging config and breaks pytest caplog assertions.

target_metadata = Base.metadata


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if not url or url.startswith("driver://"):
        path = get_settings().database_path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+pysqlite:///{path}"
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Prefer an existing connection (same StaticPool / :memory: engine as the app).
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure_and_run(connection)
        return

    url = config.get_main_option("sqlalchemy.url") or ""
    if not url or url.startswith("driver://"):
        database_path = get_settings().database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connectable = create_sqlite_engine(database_path)
    else:
        connectable = create_engine(url)

    with connectable.connect() as connection:
        _configure_and_run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
